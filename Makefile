.DEFAULT_GOAL := help

.PHONY: sync run lint format check test security ci

help: ## Show this help
	@echo "Welcome to quantagent"
	@echo ""
	@awk 'BEGIN {FS = ":.*?# "}; /^[a-zA-Z0-9_.-]+:.*?# / {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: # Install dependencies; optionally copy .env from .env.example if missing
	uv sync --group dev --link-mode=copy
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example - edit .env with your keys."; fi

run: # Run agent via TUI
	uv run quantagent 

lint: # Lint with ruff
	uv run ruff check quantagent/ tests/

format: # Format with ruff
	uv run ruff format quantagent/ tests/

fix: # Auto-fix linting issues in src and tests folders with ruff
	uv run ruff check --fix quantagent tests

check: # Lint + format check (no write)
	uv run ruff format --check quantagent/ tests/

mypy: # Run mypy type checking (package mode avoids duplicate __main__.py mapping)
	uv run mypy -pquantagent 

test: # Run tests
	uv run pytest tests/ -v

security: # Security scan with bandit
	uv run bandit -c pyproject.toml -r quantagent 

ci: check test security # Full check: lint, test, security

studio: # Run langgraph studio
	uv run langgraph dev --host 0.0.0.0
