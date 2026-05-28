import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent import explain
from .bluesky import fetch_post
from .models import ExplainRequest, ExplainResponse

load_dotenv()

logger = logging.getLogger(__name__)

_providers: dict[str, bool] = {"openai": False, "anthropic": False, "ollama": False}


async def _validate_openai() -> bool:
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            return resp.status_code == 200
    except Exception as exc:
        logger.warning("OpenAI key validation failed: %s", type(exc).__name__)
        return False


async def _validate_anthropic() -> bool:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            )
            return resp.status_code == 200
    except Exception as exc:
        logger.warning("Anthropic key validation failed: %s", type(exc).__name__)
        return False


async def _validate_ollama() -> bool:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{host}/api/tags")
            if resp.status_code != 200:
                return False
            available = [m["name"].split(":")[0] for m in resp.json().get("models", [])]
            if model.split(":")[0] not in available:
                logger.warning(
                    "Ollama is running but model '%s' is not pulled. "
                    "Run: ollama pull %s",
                    model, model,
                )
                return False
            return True
    except Exception as exc:
        logger.warning("Ollama validation failed: %s", type(exc).__name__)
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Validating API keys...")
    openai_ok, anthropic_ok, ollama_ok = await asyncio.gather(
        _validate_openai(), _validate_anthropic(), _validate_ollama()
    )
    _providers["openai"] = openai_ok
    _providers["anthropic"] = anthropic_ok
    _providers["ollama"] = ollama_ok

    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    labels = {
        "openai": "OK" if openai_ok else "missing or invalid",
        "anthropic": "OK" if anthropic_ok else "missing or invalid",
        "ollama": f"OK ({model})" if ollama_ok else "not running or model not pulled",
    }
    for name, label in labels.items():
        print(f"  {name}: {label}")

    yield


app = FastAPI(title="Bluesky Post Explainer", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/providers")
async def providers():
    ollama_ok = await _validate_ollama()
    _providers["ollama"] = ollama_ok
    return {
        "openai": _providers["openai"],
        "anthropic": _providers["anthropic"],
        "ollama": ollama_ok,
        "ollama_model": os.getenv("OLLAMA_MODEL", "llama3.2"),
    }


@app.post("/explain", response_model=ExplainResponse)
async def explain_post(req: ExplainRequest):
    if req.provider not in _providers:
        raise HTTPException(status_code=400, detail="provider must be 'openai', 'anthropic', or 'ollama'")

    if req.provider == "ollama":
        _providers["ollama"] = await _validate_ollama()

    if not _providers[req.provider]:
        raise HTTPException(
            status_code=400,
            detail=f"{req.provider} is not available — check your .env or Ollama setup",
        )

    try:
        post = await fetch_post(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch Bluesky post: {exc}")

    try:
        result = await asyncio.wait_for(explain(post, req.provider), timeout=700.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Agent timed out — try again or use a different provider")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")

    return result
