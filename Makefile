.PHONY: up clean dev eval eval-anthropic help

VENV         := backend\.venv
PY           := $(VENV)\Scripts\python.exe
UV           := $(VENV)\Scripts\uvicorn.exe
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 3000

help:
	@echo.
	@echo   up              Install deps, docker compose up --build
	@echo   clean           docker compose down + remove backend\.venv
	@echo   dev             Run backend locally with hot-reload
	@echo   eval            Run eval harness - OpenAI provider
	@echo   eval-anthropic  Run eval harness - Anthropic provider
	@echo.
	@echo   Ports (override via .env or env var):
	@echo     BACKEND_PORT=$(BACKEND_PORT)
	@echo     FRONTEND_PORT=$(FRONTEND_PORT)
	@echo.

up:
	where uv >nul 2>&1 || (powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex" && echo. && echo Installed uv — open a new terminal and run 'make up' again. && exit 1)
	if not exist $(VENV) (cd backend && uv venv --python 3.12 .venv)
	cd backend && uv pip install -r requirements.txt
	docker compose up --build

clean:
	-docker compose down -v --remove-orphans
	if exist $(VENV) rd /s /q $(VENV)

dev:
	set PYTHONPATH=backend && $(UV) app.main:app --reload --port $(BACKEND_PORT) --app-dir backend

eval:
	-set PYTHONPATH=backend && $(PY) -m evals.run_evals

eval-anthropic:
	-set PYTHONPATH=backend && set PROVIDER=anthropic && $(PY) -m evals.run_evals
