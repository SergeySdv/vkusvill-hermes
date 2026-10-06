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

.PHONY: test-protocol e2e-build e2e-smoke e2e-install
test-protocol:
	uv run --locked pytest tests/test_protocol_e2e.py
e2e-build:
	docker build -f e2e/Dockerfile -t vkusvill-hermes-e2e .
e2e-smoke: e2e-build
	uv run --locked python -m e2e.docker smoke
e2e-install: e2e-build
	uv run --locked python -m e2e.docker install

.PHONY: e2e-candidate-install
e2e-candidate-install: e2e-build
	uv run --locked python -m e2e.docker candidate-install

.PHONY: e2e-agent-suite
e2e-agent-suite: e2e-build
	test -n "$(E2E_ENV_FILE)"
	uv run --locked python -m e2e.suite --env-file "$(E2E_ENV_FILE)" --repeats 3
