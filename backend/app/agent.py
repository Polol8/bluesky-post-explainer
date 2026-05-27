import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor

import anthropic
from openai import AsyncOpenAI

from .models import BlueskyPost, Citation, ExplainResponse

_executor = ThreadPoolExecutor(max_workers=4)


def _strip_inline_citations(text: str) -> str:
    """Remove markdown inline citations like ([site.com](https://...))"""
    # ([label](url)) or ([label](url)) at end of sentences
    text = re.sub(r"\s*\(\[.*?\]\(https?://[^\)]+\)\)", "", text)
    # bare [[n]] or [n] footnote-style markers
    text = re.sub(r"\s*\[\[?\d+\]?\]", "", text)
    return text.strip()


def _parse_bullets(text: str) -> list[str]:
    """Extract up to 5 bullet points from LLM output."""
    bullets = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("• ", "- ", "* ", "· ")):
            bullets.append(_strip_inline_citations(line[2:].strip()))
        elif re.match(r"^\d+\.\s", line):
            bullets.append(_strip_inline_citations(re.sub(r"^\d+\.\s+", "", line).strip()))
    # Fallback: split on double-newlines and take non-empty chunks
    if not bullets and text.strip():
        bullets = [_strip_inline_citations(p.strip()) for p in text.strip().split("\n\n") if p.strip()]
    return [b for b in bullets if b][:5]


def _build_post_context(post: BlueskyPost) -> str:
    parts = [f'Post by @{post.author_handle} ("{post.author_display_name}"):']
    parts.append(f'"{post.text}"')
    if post.external:
        parts.append(
            f"Linked content: {post.external.title} — {post.external.description}"
        )
    if post.images:
        alt_texts = [img.alt for img in post.images if img.alt]
        parts.append(
            f"[{len(post.images)} image(s) attached"
            + (f': {"; ".join(alt_texts)}' if alt_texts else "")
            + "]"
        )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# OpenAI path — uses Responses API with built-in web_search_preview
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

    # Attach images for vision analysis (bonus feature)
    for img in post.images[:3]:
        user_content.append(
            {"type": "input_image", "image_url": img.url, "detail": "low"}
        )

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
# Anthropic path — uses tool use with DuckDuckGo search
# ---------------------------------------------------------------------------

def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    from duckduckgo_search import DDGS

    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


async def _ddg_search_async(query: str, max_results: int = 5) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _ddg_search, query, max_results)


_SEARCH_TOOL = {
    "name": "web_search",
    "description": "Search the web for context about a topic, person, or event.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query"}},
        "required": ["query"],
    },
}


async def explain_with_anthropic(post: BlueskyPost) -> ExplainResponse:
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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

    # Attach images for vision analysis (bonus feature)
    for img in post.images[:3]:
        initial_content.append(
            {"type": "image", "source": {"type": "url", "url": img.url}}
        )

    messages: list[dict] = [{"role": "user", "content": initial_content}]
    citations: list[Citation] = []

    for _ in range(6):  # max agentic loop iterations
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=(
                "You are an expert at explaining social media posts using web research. "
                "Always end with exactly 3-5 bullet points starting with '• '. "
                "Write each bullet as plain prose — no inline links, no parenthetical "
                "citations like ([site.com](url)), no footnote markers. "
                "Sources are displayed separately; do not embed them in the bullets."
            ),
            tools=[_SEARCH_TOOL],
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            output_text = next(
                (b.text for b in response.content if hasattr(b, "text")), ""
            )
            return ExplainResponse(
                bullets=_parse_bullets(output_text),
                post=post,
                citations=list({c.url: c for c in citations}.values())[:5],
                provider="anthropic",
            )

        # Execute tool calls
        tool_results = []
        for block in response.content:
            if block.type == "tool_use" and block.name == "web_search":
                query = block.input.get("query", "")
                results = await _ddg_search_async(query)
                result_text = "\n\n".join(
                    f"Title: {r.get('title', '')}\nURL: {r.get('href', '')}\n{r.get('body', '')}"
                    for r in results
                )
                for r in results[:3]:
                    if r.get("href"):
                        citations.append(
                            Citation(title=r.get("title", r["href"]), url=r["href"])
                        )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    }
                )

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("Anthropic agent did not reach end_turn in time")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def explain(post: BlueskyPost, provider: str) -> ExplainResponse:
    if provider == "anthropic":
        return await explain_with_anthropic(post)
    return await explain_with_openai(post)
