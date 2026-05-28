.PHONY: up clean dev eval eval-anthropic help

BACKEND_PORT  ?= 8000
FRONTEND_PORT ?= 3000

ifeq ($(OS),Windows_NT)
  VENV        := backend\.venv
  PY          := $(VENV)\Scripts\python.exe
  UVICORN     := $(VENV)\Scripts\uvicorn.exe
  SETPATH     := set PYTHONPATH=backend &&
  SETPROVIDER := set PROVIDER=anthropic &&
  RMVENV      := if exist $(VENV) rd /s /q $(VENV)
  BLANK       := @echo.
else
  VENV        := backend/.venv
  PY          := $(VENV)/bin/python
  UVICORN     := $(VENV)/bin/uvicorn
  SETPATH     := PYTHONPATH=backend
  SETPROVIDER := PROVIDER=anthropic
  RMVENV      := rm -rf $(VENV)
  BLANK       := @echo
endif

help:
	$(BLANK)
	@echo   up              Install deps, docker compose up --build
	@echo   clean           docker compose down + remove .venv
	@echo   dev             Run backend locally with hot-reload
	@echo   eval            Run eval harness - OpenAI provider
	@echo   eval-anthropic  Run eval harness - Anthropic provider
	$(BLANK)
	@echo   Ports (override via .env or env var):
	@echo     BACKEND_PORT=$(BACKEND_PORT)
	@echo     FRONTEND_PORT=$(FRONTEND_PORT)
	$(BLANK)

ifeq ($(OS),Windows_NT)
up:
	where uv >nul 2>&1 || (powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex" && echo. && echo Installed uv — open a new terminal and run 'make up' again. && exit 1)
	if not exist $(VENV) (cd backend && uv venv --python 3.12 .venv)
	cd backend && uv pip install -r requirements.txt
	docker compose up --build -d
	$(PY) scripts\setup_ollama.py
	docker compose logs -f

clean:
	-docker compose down -v --remove-orphans
	$(RMVENV)
else
up:
	command -v uv >/dev/null 2>&1 || (curl -LsSf https://astral.sh/uv/install.sh | sh && echo "" && echo "Installed uv — run 'source ~/.local/bin/env && make up' to continue." && exit 1)
	[ -d $(VENV) ] || (cd backend && uv venv --python 3.12 .venv)
	cd backend && uv pip install -r requirements.txt
	docker compose up --build -d
	$(PY) scripts/setup_ollama.py
	docker compose logs -f

clean:
	-docker compose down -v --remove-orphans
	$(RMVENV)
endif

dev:
	$(SETPATH) $(UVICORN) app.main:app --reload --port $(BACKEND_PORT) --app-dir backend

eval:
	-$(SETPATH) $(PY) -m evals.run_evals

eval-anthropic:
	-$(SETPATH) $(SETPROVIDER) $(PY) -m evals.run_evals
