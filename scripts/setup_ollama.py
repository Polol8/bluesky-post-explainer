"""
Called by `make up` after `docker compose up -d`.
Waits for the Ollama container to be ready, then pulls the configured model.
Skips silently if OLLAMA_MODEL is not set in .env.
"""

import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

model = os.getenv("OLLAMA_MODEL", "").strip()

if not model:
    print("Ollama: OLLAMA_MODEL not set in .env — skipping.")
    sys.exit(0)

ollama_port = os.getenv("OLLAMA_PORT", "11434").strip()
health_url = f"http://localhost:{ollama_port}/api/tags"


def wait_for_ollama(timeout: int = 60) -> bool:
    print(f"Ollama: waiting for container on port {ollama_port}...", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(health_url, timeout=2)
            return True
        except Exception:
            time.sleep(2)
    return False


def model_already_pulled() -> bool:
    try:
        r = subprocess.run(
            ["docker", "compose", "exec", "ollama", "ollama", "list"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return False
        base = model.split(":")[0]
        return any(base in line for line in r.stdout.splitlines())
    except Exception:
        return False


if not wait_for_ollama():
    print(
        f"\nOllama container did not become ready within 60 s on port {ollama_port}.\n"
        "Check `docker compose logs ollama` for details."
    )
    sys.exit(1)

if model_already_pulled():
    print(f"Ollama: model '{model}' already pulled — skipping.")
    sys.exit(0)

print(f"Ollama: pulling '{model}' into container (may take a while on first run)...")
result = subprocess.run(
    ["docker", "compose", "exec", "ollama", "ollama", "pull", model]
)
if result.returncode != 0:
    print(
        f"\nFailed to pull '{model}'.\n"
        "Check model name and try manually:\n"
        f"  docker compose exec ollama ollama pull {model}"
    )
    sys.exit(1)

print(f"Ollama: '{model}' ready.")
