import asyncio
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import anthropic
from openai import AsyncOpenAI

from .models import BlueskyPost, Citation, ExplainResponse

_executor = ThreadPoolExecutor(max_workers=4)


def _strip_inline_citations(text: str) -> str:
    text = re.sub(r"\s*\(\[.*?\]\(https?://[^\)]+\)\)", "", text)
    text = re.sub(r"\s*\[\[?\d+\]?\]", "", text)
    return text.strip()


def _parse_bullets(text: str) -> list[str]:
    bullets = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("• ", "- ", "* ", "· ")):
            bullets.append(_strip_inline_citations(line[2:].strip()))
        elif re.match(r"^\d+\.\s", line):
            bullets.append(_strip_inline_citations(re.sub(r"^\d+\.\s+", "", line).strip()))
    if not bullets and text.strip():
        bullets = [_strip_inline_citations(p.strip()) for p in text.strip().split("\n\n") if p.strip()]
    return [b for b in bullets if b][:5]


def _build_post_context(post: BlueskyPost) -> str:
    parts = [f'Post by @{post.author_handle} ("{post.author_display_name}"):']
    parts.append(f'"{post.text}"')
    if post.external:
        parts.append(f"Linked content: {post.external.title} — {post.external.description}")
    if post.images:
        alt_texts = [img.alt for img in post.images if img.alt]
        parts.append(
            f"[{len(post.images)} image(s) attached"
            + (f': {"; ".join(alt_texts)}' if alt_texts else "")
            + "]"
        )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Shared search helpers (used by Anthropic and Ollama paths)
# ---------------------------------------------------------------------------

def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    from duckduckgo_search import DDGS
    from duckduckgo_search.exceptions import DuckDuckGoSearchException
    for attempt in range(3):
        try:
            with DDGS(timeout=10) as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except DuckDuckGoSearchException as exc:
            if "202" not in str(exc) and "atelimit" not in str(exc):
                raise
            if attempt == 2:
                return []
            time.sleep(2 ** attempt)
    return []


async def _ddg_search_async(query: str, max_results: int = 5) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _ddg_search, query, max_results)


def _ddg_results_to_text(results: list[dict]) -> str:
    return "\n\n".join(
        f"Title: {r.get('title', '')}\nURL: {r.get('href', '')}\n{r.get('body', '')}"
        for r in results
    )


def _collect_citations(results: list[dict]) -> list[Citation]:
    return [
        Citation(title=r.get("title", r["href"]), url=r["href"])
        for r in results[:3]
        if r.get("href")
    ]


# ---------------------------------------------------------------------------
# OpenAI path — Responses API with built-in web_search_preview
# ---------------------------------------------------------------------------

async def explain_with_openai(post: BlueskyPost) -> ExplainResponse:
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    user_content: list[dict] = [
        {
            "type": "input_text",
            "text": (
                "Here is a Bluesky post:\n\n"
                + _build_post_context(post)
                + "\n\nSearch the web for relevant context, then return exactly 3-5 bullet "
                "points (starting with '• ') explaining: what the post is about, who or what "
                "is being referenced, and why it matters.\n\n"
                "Rules:\n"
                "- Write each bullet as plain prose — no inline links, no parenthetical "
                "citations like ([site.com](url)), no footnote markers.\n"
                "- Sources are displayed separately; do not embed them in the bullets."
            ),
        }
    ]

    for img in post.images[:3]:
        user_content.append({"type": "input_image", "image_url": img.url, "detail": "low"})

    response = await client.responses.create(
        model="gpt-4o",
        tools=[{"type": "web_search_preview"}],
        input=[{"role": "user", "content": user_content}],
    )

    output_text = ""
    citations: list[Citation] = []

    for item in response.output:
        if item.type == "message":
            for block in item.content:
                if block.type == "output_text":
                    output_text = block.text
                    for ann in getattr(block, "annotations", []):
                        if ann.type == "url_citation":
                            citations.append(Citation(title=ann.title, url=ann.url))

    return ExplainResponse(
        bullets=_parse_bullets(output_text),
        post=post,
        citations=list({c.url: c for c in citations}.values())[:5],
        provider="openai",
    )


# ---------------------------------------------------------------------------
# Anthropic path — tool use with DuckDuckGo search
# ---------------------------------------------------------------------------

_ANTHROPIC_SEARCH_TOOL = {
    "name": "web_search",
    "description": "Search the web for context about a topic, person, or event.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query"}},
        "required": ["query"],
    },
}

_SYSTEM_PROMPT = (
    "You are an expert at explaining social media posts using web research. "
    "Always end with exactly 3-5 bullet points starting with '• '. "
    "Write each bullet as plain prose — no inline links, no parenthetical "
    "citations like ([site.com](url)), no footnote markers. "
    "Sources are displayed separately; do not embed them in the bullets."
)


async def explain_with_anthropic(post: BlueskyPost) -> ExplainResponse:
    client = anthropic.AsyncAnthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=30.0,
    )

    initial_content: list[dict] = [
        {
            "type": "text",
            "text": (
                "Search the web for context, then explain this Bluesky post with exactly "
                "3-5 bullet points (starting with '• ').\n\n"
                + _build_post_context(post)
            ),
        }
    ]

    for img in post.images[:3]:
        initial_content.append({"type": "image", "source": {"type": "url", "url": img.url}})

    messages: list[dict] = [{"role": "user", "content": initial_content}]
    citations: list[Citation] = []

    for _ in range(6):
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=[_ANTHROPIC_SEARCH_TOOL],
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            output_text = next((b.text for b in response.content if hasattr(b, "text")), "")
            return ExplainResponse(
                bullets=_parse_bullets(output_text),
                post=post,
                citations=list({c.url: c for c in citations}.values())[:5],
                provider="anthropic",
            )

        tool_results = []
        for block in response.content:
            if block.type == "tool_use" and block.name == "web_search":
                results = await _ddg_search_async(block.input.get("query", ""))
                citations.extend(_collect_citations(results))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _ddg_results_to_text(results),
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("Anthropic agent did not reach end_turn in time")


# ---------------------------------------------------------------------------
# Ollama path — pre-search with DuckDuckGo, single LLM call (no tool schema)
# Works with any model regardless of function-calling support.
# ---------------------------------------------------------------------------

async def explain_with_ollama(post: BlueskyPost) -> ExplainResponse:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")

    query = post.text[:200]
    if post.external:
        query += f" {post.external.title}"

    results = await _ddg_search_async(query)
    citations = _collect_citations(results)
    search_context = _ddg_results_to_text(results)

    import httpx

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{host}/api/chat",
            json={
                "model": model,
                "think": False,
                "stream": False,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Here is a Bluesky post to explain:\n\n"
                            + _build_post_context(post)
                            + "\n\nWeb search results for context:\n\n"
                            + search_context
                            + "\n\nNow write exactly 3-5 bullet points (starting with '• ') "
                            "explaining what the post is about, who or what is referenced, "
                            "and why it matters."
                        ),
                    },
                ],
            },
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]

    return ExplainResponse(
        bullets=_parse_bullets(content),
        post=post,
        citations=list({c.url: c for c in citations}.values())[:5],
        provider=f"ollama/{model}",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def explain(post: BlueskyPost, provider: str) -> ExplainResponse:
    if provider == "anthropic":
        return await explain_with_anthropic(post)
    if provider == "ollama":
        return await explain_with_ollama(post)
    return await explain_with_openai(post)
