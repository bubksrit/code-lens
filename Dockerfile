# Multi-stage Dockerfile for PRISM Agentic Code Intelligence
FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definition
COPY pyproject.toml .env.example ./

# Install python dependencies
RUN pip install --no-cache-dir fastapi uvicorn pydantic pydantic-settings python-dotenv httpx pytest

# Copy application source code
COPY backend/ ./backend/
COPY data/ ./data/

ENV PYTHONPATH=/app
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
