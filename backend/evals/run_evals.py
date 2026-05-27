"""
Eval harness for the Bluesky Post Explainer agent.

Usage:
    python -m evals.run_evals                      # default: openai, localhost
    PROVIDER=anthropic python -m evals.run_evals
    API_URL=http://my-host:8000 python -m evals.run_evals
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000")
PROVIDER = os.getenv("PROVIDER", "openai")
PASS_THRESHOLD = 0.5  # fraction of expected_topics that must appear


def score(bullets: list[str], expected_topics: list[str]) -> float:
    """Return fraction of expected_topics found anywhere in the bullets."""
    if not expected_topics:
        return 1.0
    text = " ".join(bullets).lower()
    matched = sum(1 for t in expected_topics if t.lower() in text)
    return matched / len(expected_topics)


async def run_case(client: httpx.AsyncClient, case: dict) -> dict:
    try:
        resp = await client.post(
            f"{API_URL}/explain",
            json={"url": case["url"], "provider": PROVIDER},
            timeout=90.0,
        )
        resp.raise_for_status()
        data = resp.json()
        bullets = data["bullets"]
        s = score(bullets, case.get("expected_topics", []))
        return {
            "id": case["id"],
            "description": case["description"],
            "score": s,
            "passed": s >= PASS_THRESHOLD,
            "bullets": bullets,
            "num_citations": len(data.get("citations", [])),
            "error": None,
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "description": case["description"],
            "score": 0.0,
            "passed": False,
            "bullets": [],
            "num_citations": 0,
            "error": str(exc),
        }


def print_result(r: dict) -> None:
    status = "PASS" if r["passed"] else "FAIL"
    print(f"[{status}] {r['id']}")
    print(f"       {r['description']}")
    if r["error"]:
        print(f"       ERROR: {r['error']}")
    else:
        print(f"       Score: {r['score']:.0%}  Citations: {r['num_citations']}")
        for b in r["bullets"]:
            print(f"       • {b}")
    print()


async def main() -> None:
    cases_path = Path(__file__).parent / "test_cases.json"
    cases: list[dict] = json.loads(cases_path.read_text())

    print(f"Bluesky Post Explainer — Eval Harness")
    print(f"Provider : {PROVIDER}")
    print(f"API      : {API_URL}")
    print(f"Cases    : {len(cases)}\n")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        # Run sequentially to avoid hammering the API / search providers
        results = []
        for case in cases:
            print(f"Running: {case['id']} ...", flush=True)
            result = await run_case(client, case)
            results.append(result)

    print("\n" + "=" * 60 + "\n")
    for r in results:
        print_result(r)

    passed = sum(1 for r in results if r["passed"])
    avg = sum(r["score"] for r in results) / len(results)
    print("=" * 60)
    print(f"Passed : {passed}/{len(results)}")
    print(f"Avg    : {avg:.0%}")

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
