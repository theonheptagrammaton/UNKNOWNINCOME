# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies + app (single image; api/worker differ only by command).
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

# Build metadata — compose passes the short git sha.
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
