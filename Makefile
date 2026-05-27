.PHONY: up clean dev eval eval-anthropic help

VENV := backend\.venv
PY   := $(VENV)\Scripts\python.exe
UV   := $(VENV)\Scripts\uvicorn.exe

help:
	@echo.
	@echo   up              Create .venv, install deps, docker compose up --build
	@echo   clean           docker compose down + remove backend\.venv
	@echo   dev             Run backend locally with hot-reload
	@echo   eval            Run eval harness - OpenAI provider
	@echo   eval-anthropic  Run eval harness - Anthropic provider
	@echo.

up:
	cd backend && uv venv .venv
	cd backend && uv pip install -r requirements.txt
	docker compose up --build

clean:
	-docker compose down -v --remove-orphans
	if exist $(VENV) rd /s /q $(VENV)

dev:
	set PYTHONPATH=backend && $(UV) app.main:app --reload --port 8000 --app-dir backend

eval:
	-set PYTHONPATH=backend && $(PY) -m evals.run_evals

eval-anthropic:
	-set PYTHONPATH=backend && set PROVIDER=anthropic && $(PY) -m evals.run_evals
