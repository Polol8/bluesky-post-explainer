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
from datetime import datetime, timezone
from pathlib import Path

import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000")
PROVIDER = os.getenv("PROVIDER", "openai")
PASS_THRESHOLD = 0.5  # fraction of expected_topics that must appear

REPORT_PATH = Path(__file__).parent / "results.md"


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
        citations = data.get("citations", [])
        s = score(bullets, case.get("expected_topics", []))
        return {
            "id": case["id"],
            "description": case["description"],
            "url": case["url"],
            "score": s,
            "passed": s >= PASS_THRESHOLD,
            "bullets": bullets,
            "citations": citations,
            "error": None,
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "description": case["description"],
            "url": case["url"],
            "score": 0.0,
            "passed": False,
            "bullets": [],
            "citations": [],
            "error": str(exc),
        }


def print_result(r: dict) -> None:
    status = "PASS" if r["passed"] else "FAIL"
    print(f"[{status}] {r['id']}")
    print(f"       {r['description']}")
    if r["error"]:
        print(f"       ERROR: {r['error']}")
    else:
        print(f"       Score: {r['score']:.0%}  Citations: {len(r['citations'])}")
        for b in r["bullets"]:
            print(f"       • {b}")
    print()


def write_report(results: list[dict], passed: int, avg: float) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []

    lines += [
        f"# Eval Report",
        f"",
        f"| | |",
        f"|---|---|",
        f"| Date | {now} |",
        f"| Provider | `{PROVIDER}` |",
        f"| API | `{API_URL}` |",
        f"| Passed | **{passed}/{len(results)}** |",
        f"| Avg score | **{avg:.0%}** |",
        f"",
        f"---",
        f"",
    ]

    for r in results:
        badge = "✅ PASS" if r["passed"] else "❌ FAIL"
        lines += [
            f"## {badge} — {r['id']}",
            f"",
            f"**{r['description']}**  ",
            f"[{r['url']}]({r['url']})",
            f"",
        ]

        if r["error"]:
            lines += [f"> **Error:** {r['error']}", f""]
        else:
            lines += [f"Score: `{r['score']:.0%}` | Citations: `{len(r['citations'])}`", f""]
            for b in r["bullets"]:
                lines.append(f"- {b}")
            lines.append("")
            if r["citations"]:
                lines.append("**Sources**")
                for c in r["citations"]:
                    lines.append(f"- [{c['title']}]({c['url']})")
                lines.append("")

        lines.append("---")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report saved → {REPORT_PATH}")


async def main() -> None:
    cases_path = Path(__file__).parent / "test_cases.json"
    cases: list[dict] = json.loads(cases_path.read_text())

    print(f"Bluesky Post Explainer — Eval Harness")
    print(f"Provider : {PROVIDER}")
    print(f"API      : {API_URL}")
    print(f"Cases    : {len(cases)}\n")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
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

    write_report(results, passed, avg)

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
