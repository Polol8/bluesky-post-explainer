import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent import explain
from .bluesky import fetch_post
from .models import ExplainRequest, ExplainResponse

load_dotenv()

app = FastAPI(title="Bluesky Post Explainer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/explain", response_model=ExplainResponse)
async def explain_post(req: ExplainRequest):
    if req.provider not in ("openai", "anthropic"):
        raise HTTPException(status_code=400, detail="provider must be 'openai' or 'anthropic'")

    try:
        post = await fetch_post(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch Bluesky post: {exc}")

    if req.provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY is not configured")

    try:
        result = await explain(post, req.provider)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")

    return result
