# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.14 AS uv
FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app/backend

FROM runtime AS dependencies

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

FROM dependencies AS gigachat-dependencies

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --extra gigachat

FROM runtime AS gigachat

COPY --from=gigachat-dependencies /opt/venv /opt/venv
USER 10001:10001
EXPOSE 8090
CMD ["gpt2giga"]

FROM runtime AS game

COPY --from=dependencies /opt/venv /opt/venv
COPY backend/consequences_model ./consequences_model
COPY backend/negotiation_game ./negotiation_game
COPY backend/web_backend ./web_backend
COPY backend/assets ./assets
COPY backend/full_embeddings.jsonl ./
COPY frontend /app/frontend

RUN install -d -o 10001 -g 10001 /var/lib/city-n/runs
ENV CITY_N_RUNS_DIR=/var/lib/city-n/runs
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "web_backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
