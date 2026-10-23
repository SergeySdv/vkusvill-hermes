ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
RUN pip install --no-cache-dir uv==0.12.23
WORKDIR /opt/vv
ENV UV_COMPILE_BYTECODE=1 PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --extra broker --no-dev --no-editable \
    && groupadd --gid 10001 vv-auth \
    && useradd --uid 10001 --gid 10001 --no-create-home vv-auth
USER 10001:10001
ENTRYPOINT ["/opt/vv/.venv/bin/vv-auth-web"]
CMD ["--config", "/run/secrets/broker.json", "--host", "0.0.0.0"]
