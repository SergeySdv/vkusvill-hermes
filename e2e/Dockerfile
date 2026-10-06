FROM nousresearch/hermes-agent@sha256:d4da4a40cd7a28aba983775d9fd31d94cbf153eeb0cb9e844d6d0f612b7c24db
USER root
WORKDIR /opt/candidate
COPY . .
RUN /opt/hermes/.venv/bin/python -m venv /opt/vv && \
    /opt/vv/bin/pip install --no-cache-dir uv==0.12.23 && \
    UV_PROJECT_ENVIRONMENT=/opt/vv /opt/vv/bin/uv sync --locked --python /opt/vv/bin/python
ENV PATH="/opt/vv/bin:${PATH}"
USER hermes
