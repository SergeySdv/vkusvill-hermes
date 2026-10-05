.PHONY: setup lint format test check build
setup:
	uv sync --locked
lint:
	uv run --locked ruff check .
	uv run --locked ruff format --check .
format:
	uv run --locked ruff check --fix .
	uv run --locked ruff format .
test:
	uv run --locked pytest
check: lint test
build:
	uv build
