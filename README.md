# Bluesky Post Explainer

AI agent that explains Bluesky posts by surfacing relevant web context. Paste a post URL and get 3-5 bullet points explaining what it references, why it matters, and who is involved.

## Demo

> Input: `https://bsky.app/profile/wiiiiics.bsky.social/post/3lfqkfbkbes2k`
>
> Output:
> - The "Ralph Wiggum technique" is a bash-loop pattern that repeatedly runs an AI coding agent until the task completes, named after the Simpsons character known for bumbling persistence.
> - Coined by Geoffrey Huntley in mid-2025, the name stuck because the community found it funny rather than technical — "I'm in danger" became a meme for agentic AI loops.
> - The technique gained traction as a minimal alternative to complex orchestration frameworks like LangGraph or AutoGPT.

---

## Architecture

```
bluesky-context/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI — POST /explain, GET /health
│   │   ├── agent.py          # LLM orchestration (OpenAI + Anthropic paths)
│   │   ├── bluesky.py        # AT Protocol public API client
│   │   └── models.py         # Pydantic request/response models
│   ├── evals/
│   │   ├── test_cases.json   # 12 posts with expected_topics
│   │   └── run_evals.py      # Eval harness runner
│   ├── .venv/                # Created by `make up` (not committed)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html            # Single-page UI
│   ├── style.css
│   └── app.js
├── nginx.conf                # Proxies /api/* → backend container
├── docker-compose.yml
├── Makefile
└── .env.example
```

## System Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser  (localhost:3000)                                       │
│                                                                  │
│  [ Bluesky post URL ] + [ Provider: OpenAI | Anthropic ]        │
│                │                                                 │
│                │  POST /api/explain                              │
└────────────────┼────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  nginx  (routes /api/* → backend:8000)                          │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI  backend  (app/main.py)                                 │
│                                                                  │
│  1. bluesky.py — resolve handle → DID via AT Protocol API       │
│                  fetch post thread (text, images, embeds)        │
│                                                                  │
│  2. agent.py  — choose provider path                            │
│                                                                  │
│     ┌─── OpenAI path ───────────────────────────────────┐       │
│     │                                                    │       │
│     │  Responses API  (gpt-4o)                          │       │
│     │    ├─ input: post text + image URLs (vision)      │       │
│     │    ├─ tool:  web_search_preview  (built-in)       │       │
│     │    │         searches → synthesizes internally    │       │
│     │    └─ output: bullets + url_citation annotations  │       │
│     │                                                    │       │
│     └────────────────────────────────────────────────────┘       │
│                                                                  │
│     ┌─── Anthropic path ────────────────────────────────┐       │
│     │                                                    │       │
│     │  Messages API  (claude-sonnet-4-6)                │       │
│     │    ├─ input: post text + image URLs (vision)      │       │
│     │    ├─ tool:  web_search  (custom)                 │       │
│     │    │    └─ DuckDuckGo search  (no extra key)      │       │
│     │    ├─ agentic loop until stop_reason=end_turn     │       │
│     │    └─ output: bullets  (citations from DDG URLs)  │       │
│     │                                                    │       │
│     └────────────────────────────────────────────────────┘       │
│                                                                  │
│  3. Return  { bullets, post, citations, provider }              │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  Browser  renders                                                │
│    • Post card  (author, text, images, stats)                   │
│    • 3-5 context bullets                                         │
│    • Sources list  (linked citations)                            │
└─────────────────────────────────────────────────────────────────┘
```

## Design Decisions

**Why two LLM providers?**
OpenAI's Responses API has `web_search_preview` built in — one call handles searching and synthesizing, with citations as structured annotations. For Anthropic, there is no built-in search, so the agent uses Claude's tool-use loop with DuckDuckGo (no extra API key needed). This shows both architectures cleanly.

**Why the OpenAI Responses API instead of Chat Completions?**
The Responses API surfaces URL citations as typed annotations on the output text, making citation extraction reliable without regex hacks. It also handles multi-turn search internally, reducing code complexity.

**Why DuckDuckGo for the Anthropic path?**
It requires no additional API key, making the Anthropic path self-contained (only `ANTHROPIC_API_KEY` needed). For production, swapping in Tavily or Serper is a one-line change in `agent.py`.

**Bullet parsing**
Both providers are prompted to output lines starting with `• `. The `_parse_bullets` function in `agent.py` also handles numbered lists and paragraph fallback, so formatting quirks don't break the response.

**Image understanding (bonus)**
If the post contains images, their CDN URLs are attached to the LLM call. OpenAI receives them as `input_image` blocks; Anthropic as `image / source.url` blocks. Both use the model's vision capability without downloading bytes server-side.

**Eval scoring**
Each test case lists `expected_topics` — keywords that should appear somewhere in the returned bullets. A case passes at ≥ 50% topic coverage. This is intentionally lenient because the agent may surface a topic using different wording.

---

## Setup

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — Python package manager
- Docker & Docker Compose
- An OpenAI API key

### 1. Configure environment

```
copy .env.example .env
# Edit .env — add OPENAI_API_KEY (and optionally ANTHROPIC_API_KEY)
```

### 2. Start everything

```
make up
```

This single command:
1. Creates `backend/.venv` via `uv venv`
2. Installs all dependencies via `uv pip install`
3. Runs `docker compose up --build` (backend on `:8000`, frontend on `:3000`)

Open `http://localhost:3000` in your browser.

### Stop & clean up

```
make clean
```

Runs `docker compose down` and removes `backend/.venv`.

---

## Local Development

To run the backend with hot-reload outside Docker:

```
make dev
```

Then open `frontend/index.html` directly in your browser — the JS detects it's not on port 3000 and calls `http://localhost:8000` directly.

---

## Eval Harness

`evals/test_cases.json` contains 12 Bluesky posts with `expected_topics` keywords used for scoring.

> **Note:** Post URLs may be deleted over time. Verify or replace URLs in `test_cases.json` before running.

```
# OpenAI provider (default)
make eval

# Anthropic provider
make eval-anthropic

# Against a remote backend
set API_URL=https://my-host.example.com && make eval
```

The harness prints pass/fail per case and exits with code `1` if any case fails.

---

## Bonus Features

| Feature | Status |
|---|---|
| Image understanding (GPT-4o vision / Claude vision) | Included |
| Multi-provider comparison (OpenAI vs Anthropic) | Included |
| URL citations with source attribution | Included |

---

## API Reference

### `POST /explain`

```json
{
  "url": "https://bsky.app/profile/handle.bsky.social/post/rkey",
  "provider": "openai"
}
```

Response:

```json
{
  "bullets": ["...", "..."],
  "post": {
    "uri": "at://...",
    "text": "...",
    "author_handle": "handle.bsky.social",
    "author_display_name": "Display Name",
    "created_at": "2025-01-05T22:56:00.000Z",
    "images": [],
    "external": null,
    "likes": 1800,
    "reposts": 92,
    "replies": 80
  },
  "citations": [{"title": "...", "url": "https://..."}],
  "provider": "openai"
}
```

### `GET /health`

Returns `{"status": "ok"}`.
