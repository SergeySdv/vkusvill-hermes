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

.PHONY: pilot-bundle
pilot-bundle:
	test -n "$(PILOT_OUTPUT)"
	uv run --locked python deploy/jarvis/build_bundle.py --output "$(PILOT_OUTPUT)"

.PHONY: test-broker broker-build broker-smoke
test-broker:
	uv run --locked pytest tests/test_broker.py tests/test_broker_hardening.py
.PHONY: broker-browser
broker-browser:
	uv run --locked --group browser pytest tests/test_broker_browser.py
.PHONY: broker-containers
broker-containers:
	uv run --locked python -m e2e.broker_containers
broker-build:
	docker build -f deploy/broker/Dockerfile -t vv-auth-candidate .
broker-smoke:
	docker run --rm --read-only --network none --cap-drop ALL \
		--security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=16m \
		-v "$(CURDIR)/e2e/broker_smoke.py:/test/broker_smoke.py:ro" \
		--entrypoint /opt/vv/.venv/bin/python vv-auth-candidate /test/broker_smoke.py

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

.PHONY: release-check
release-check: e2e-build
	uv run --locked python -m e2e.docker release

.PHONY: e2e-agent-suite
e2e-agent-suite: e2e-build
	test -n "$(E2E_ENV_FILE)"
	uv run --locked python -m e2e.suite --env-file "$(E2E_ENV_FILE)" --repeats 3
