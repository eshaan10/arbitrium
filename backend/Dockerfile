# syntax=docker/dockerfile:1
# NOTE: build context is the repo root (see docker-compose.yml) so that both the
# backend package and the db/migrations tree are available in the image.
FROM python:3.11-slim

# uv for fast, cache-friendly installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

# Copy the whole repo (backend + db/migrations), then install the backend package
# in editable mode. Editable target /app/backend matches the runtime bind mount.
COPY . .
RUN uv pip install --system --no-cache -e "./backend[dev]"

EXPOSE 8000
CMD ["uvicorn", "marketedge.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
