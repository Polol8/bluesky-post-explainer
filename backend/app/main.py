import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent import explain
from .bluesky import fetch_post
from .models import ExplainRequest, ExplainResponse

load_dotenv()

logger = logging.getLogger(__name__)

# Populated at startup after live key validation
_providers: dict[str, bool] = {"openai": False, "anthropic": False}


async def _validate_openai() -> bool:
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        return False
    try:
        import httpx
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
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            )
            return resp.status_code == 200
    except Exception as exc:
        logger.warning("Anthropic key validation failed: %s", type(exc).__name__)
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Validating API keys...")
    openai_ok, anthropic_ok = await asyncio.gather(
        _validate_openai(), _validate_anthropic()
    )
    _providers["openai"] = openai_ok
    _providers["anthropic"] = anthropic_ok

    for name, ok in _providers.items():
        mark = "OK" if ok else "missing or invalid"
        print(f"  {name}: {mark}")

    if not any(_providers.values()):
        logger.error("No valid API keys found — /explain will be unavailable.")

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
    return _providers


@app.post("/explain", response_model=ExplainResponse)
async def explain_post(req: ExplainRequest):
    if req.provider not in _providers:
        raise HTTPException(status_code=400, detail="provider must be 'openai' or 'anthropic'")

    if not _providers[req.provider]:
        raise HTTPException(
            status_code=400,
            detail=f"{req.provider} API key is missing or invalid",
        )

    try:
        post = await fetch_post(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch Bluesky post: {exc}")

    try:
        result = await explain(post, req.provider)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")

    return result
