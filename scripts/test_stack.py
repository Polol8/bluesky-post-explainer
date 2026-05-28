"""
Quick smoke-test for DDG search and Ollama inference.
Usage: python scripts/test_stack.py
"""

import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")
TEST_QUERY = "Qwen AI model release"

PASS = "[PASS]"
FAIL = "[FAIL]"


def test_ddg():
    print("-- DDG search -----------------------------")
    try:
        from duckduckgo_search import DDGS
        from duckduckgo_search.exceptions import DuckDuckGoSearchException

        t0 = time.time()
        with DDGS(timeout=10) as ddgs:
            results = list(ddgs.text(TEST_QUERY, max_results=3))
        elapsed = time.time() - t0

        if results:
            print(f"  {PASS}  {len(results)} result(s) in {elapsed:.1f}s")
            print(f"         First: {results[0].get('title', '')[:60]}")
        else:
            print(f"  {FAIL}  No results returned in {elapsed:.1f}s")
        return bool(results)

    except Exception as exc:
        print(f"  {FAIL}  {type(exc).__name__}: {exc}")
        return False


def test_ollama_health():
    print("-- Ollama health --------------------------")
    try:
        url = f"http://localhost:{OLLAMA_PORT}/api/tags"
        t0 = time.time()
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        elapsed = time.time() - t0
        models = [m["name"] for m in data.get("models", [])]
        print(f"  {PASS}  reachable in {elapsed:.2f}s — models: {models or '(none)'}")
        model_base = OLLAMA_MODEL.split(":")[0]
        if not any(model_base in m for m in models):
            print(f"  WARN  '{OLLAMA_MODEL}' not in list — run: ollama pull {OLLAMA_MODEL}")
        return True
    except Exception as exc:
        print(f"  {FAIL}  {type(exc).__name__}: {exc}")
        return False


def test_ollama_inference():
    print("-- Ollama inference (native API, think=false) --")
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": "Reply with exactly one word: OK"}],
        "stream": False,
        "think": False,
        "options": {"num_predict": 20},
    }).encode()
    req = urllib.request.Request(
        f"http://localhost:{OLLAMA_PORT}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        elapsed = time.time() - t0
        content = data["message"]["content"]
        print(f"  {PASS}  responded in {elapsed:.1f}s")
        print(f"         Content: {content[:80]!r}")
        return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:200]
        print(f"  {FAIL}  HTTP {exc.code}: {body}")
        return False
    except Exception as exc:
        print(f"  {FAIL}  {type(exc).__name__}: {exc}")
        return False


if __name__ == "__main__":
    print(f"\nBluesky-context stack test  (model={OLLAMA_MODEL})\n")
    ddg_ok = test_ddg()
    ollama_health = test_ollama_health()
    ollama_inf = test_ollama_inference()

    results = [ddg_ok, ollama_health, ollama_inf]
    print()
    total = len(results)
    passed = sum(results)

    if not ddg_ok:
        print("NOTE: DDG rate-limited — searches will return [] (agent still works without search context)")
    status = PASS if ollama_health and ollama_inf else FAIL
    print(f"Result: {status}  {passed}/{total} passed\n")
    sys.exit(0 if (ollama_health and ollama_inf) else 1)
