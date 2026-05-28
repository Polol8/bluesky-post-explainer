# Bluesky Post Explainer

AI agent that explains Bluesky posts by surfacing relevant web context. Paste a post URL and get 3-5 bullet points explaining what it references, why it matters, and who is involved.

## Demo

> Input: `https://bsky.app/profile/theverge.com/post/3mmsbh3ogxk25`
>
> Post: *"Did the Pope use AI to warn us about the dangers of AI?"*
>
> Output:
> - In January 2025, Pope Francis released *Antiqua et Nova*, the first papal document dedicated entirely to artificial intelligence, warning of threats to human dignity, democracy, and truth.
> - The encyclical's unusually polished and technically precise language sparked widespread speculation that it may have been drafted with AI assistance — an irony that went viral given its critical tone toward the technology.
> - The Vatican denied using AI in its composition, but the controversy itself became a major part of the story, drawing responses from ethicists, journalists, and tech leaders.
> - The document calls on governments and companies to ground AI development in ethical principles and human oversight, framing it as a moral rather than purely technical challenge.
> - It is considered the most influential religious statement on AI to date and was cited in multiple international AI governance debates throughout 2025.

---

## Architecture

```
bluesky-context/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI — POST /explain, GET /providers, GET /health
│   │   ├── agent.py          # LLM orchestration (OpenAI + Anthropic + Ollama)
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
├── scripts/
│   ├── setup_ollama.py       # Pulls + warms up the Ollama model after `make up`
│   └── test_stack.py         # Smoke-tests DDG search and Ollama inference
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
│  [ Bluesky post URL ] + [ Provider: OpenAI | Anthropic | Ollama]│
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
│     ┌─── Ollama path ───────────────────────────────────┐       │
│     │                                                    │       │
│     │  Local model  (configurable via OLLAMA_MODEL)     │       │
│     │    ├─ DuckDuckGo pre-search (no extra key)        │       │
│     │    │    └─ results injected into prompt           │       │
│     │    ├─ /api/chat  (Ollama native, think=false)     │       │
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

**Why three LLM providers?**
OpenAI's Responses API has `web_search_preview` built in — one call handles searching and synthesizing, with citations as structured annotations. For Anthropic, there is no built-in search, so the agent uses Claude's tool-use loop with DuckDuckGo (no extra API key needed). Ollama adds a fully local, zero-cost option for users who want to run inference on their own hardware.

**Why the OpenAI Responses API instead of Chat Completions?**
The Responses API surfaces URL citations as typed annotations on the output text, making citation extraction reliable without regex hacks. It also handles multi-turn search internally, reducing code complexity.

**Why DuckDuckGo for the Anthropic and Ollama paths?**
It requires no additional API key, making both paths self-contained. For production, swapping in Tavily or Serper is a one-line change in `agent.py`. The `ddgs` package is used (the official successor to `duckduckgo-search`); if DDG rate-limits a request, the agent falls back gracefully to responding without search context rather than failing.

**Why the Ollama native API instead of the OpenAI-compatible endpoint?**
Ollama's `/api/chat` endpoint exposes the `think` parameter, which disables extended chain-of-thought reasoning in models like Qwen3. The OpenAI-compatible shim does not pass this option through. Without `think: false`, a 0.8B model can spend several minutes generating reasoning tokens before producing any output.

**Bullet parsing**
All providers are prompted to output lines starting with `• `. The `_parse_bullets` function in `agent.py` also handles numbered lists and paragraph fallback, so formatting quirks don't break the response.

**Image understanding**
If the post contains images, their CDN URLs are attached to the LLM call. OpenAI receives them as `input_image` blocks; Anthropic as `image / source.url` blocks. Ollama does not receive images (most local models lack reliable vision support).

**API key validation at startup**
On boot, the backend validates each API key with a live HTTP request to the provider. The result is stored in `_providers` and exposed via `GET /providers`. The frontend reads this on page load and disables radio buttons for unavailable providers — no silent failures.

**Eval scoring**
Each test case lists `expected_topics` — keywords that should appear somewhere in the returned bullets. A case passes at ≥ 50% topic coverage. This is intentionally lenient because the agent may surface a topic using different wording.

---

## Setup

### Prerequisites

- Docker & Docker Compose
- At least one of: an OpenAI API key, an Anthropic API key, or enough RAM to run a local model via Ollama

`make up` installs [uv](https://docs.astral.sh/uv/) automatically if it is not found, and uses it to manage Python and the virtualenv.

### 1. Configure environment

```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

Edit `.env` and add your API key(s):

```env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...   # optional

# Local model via Ollama (optional — leave blank to disable)
OLLAMA_MODEL=qwen3.5:0.8b
```

Any model available on [ollama.com/library](https://ollama.com/library) can be used. Smaller models (`0.5b`–`1.5b`) run on CPU; larger ones benefit from a GPU.

### 2. Start everything

```bash
make up
```

This single command:
1. Installs `uv` if missing (via the official installer)
2. Creates `backend/.venv` with Python 3.12 if it does not already exist
3. Installs all Python dependencies
4. Runs `docker compose up --build` (backend on `:8000`, frontend on `:3000`, Ollama on `:11434`)
5. Pulls the configured Ollama model and runs a warmup inference so the first real request is fast

Open `http://localhost:3000` in your browser.

> **First run only:** if `uv` was just installed, open a new terminal and run `make up` again (Windows), or run `source ~/.local/bin/env && make up` (Linux/macOS).

### Stop & clean up

```bash
make clean
```

Runs `docker compose down` and removes `backend/.venv`.

---

## Configuring Ports

Ports can be overridden in `.env`:

```env
BACKEND_PORT=8001
FRONTEND_PORT=3001
OLLAMA_PORT=11435
```

---

## Local Development

To run the backend with hot-reload outside Docker:

```bash
make dev
```

Then open `frontend/index.html` directly in your browser — the JS detects it is not being served on port 3000 and calls `http://localhost:8000` directly.

---

## Smoke Tests

`scripts/test_stack.py` verifies DDG search and Ollama inference independently of the full Docker stack:

```bash
# From the project root
backend/.venv/Scripts/python.exe scripts/test_stack.py   # Windows
backend/.venv/bin/python scripts/test_stack.py           # Linux / macOS
```

---

## Eval Harness

`evals/test_cases.json` contains 12 real Bluesky posts with `expected_topics` keywords used for scoring.

> **Note:** Post URLs may be deleted over time. Verify or replace URLs in `test_cases.json` before running.

```bash
# OpenAI provider (default)
make eval

# Anthropic provider
make eval-anthropic

# Against a remote backend
API_URL=https://my-host.example.com make eval   # Linux
set API_URL=https://my-host.example.com && make eval   # Windows
```

The harness prints pass/fail per case and writes a markdown report to `backend/evals/results.md`.

---

## Bonus Features

| Feature | Status |
|---|---|
| Image understanding (GPT-4o vision / Claude vision) | Included |
| Multi-provider support (OpenAI, Anthropic, Ollama) | Included |
| Local model inference via Ollama (zero API cost) | Included |
| URL citations with source attribution | Included |
| Provider availability shown in UI (disabled if key missing) | Included |
| DuckDuckGo search with rate-limit resilience | Included |
| Configurable ports via `.env` | Included |
| Cross-platform Makefile (Windows + Linux/macOS) | Included |

---

## API Reference

### `POST /explain`

```json
{
  "url": "https://bsky.app/profile/handle.bsky.social/post/rkey",
  "provider": "openai"
}
```

`provider` accepts `"openai"`, `"anthropic"`, or `"ollama"`.

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

### `GET /providers`

Returns which providers are available based on startup key validation:

```json
{
  "openai": true,
  "anthropic": false,
  "ollama": true,
  "ollama_model": "qwen3.5:0.8b"
}
```

### `GET /health`

Returns `{"status": "ok"}`.
