# syntax=docker/dockerfile:1

# ============================================================
# Production Dockerfile for Leads Agent
# ============================================================

FROM python:3.11-slim

WORKDIR /app

# Install uv and create non-root user
RUN pip install --no-cache-dir uv \
    && useradd --create-home --shell /bin/bash appuser

# Copy app + credentials (credentials are expected to exist at repo root: .logfire/)
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY .logfire/ ./.logfire/

# Install dependencies and the package (NOT editable for production)
RUN uv pip install --system --no-cache . \
    && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Environment defaults (override at runtime)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    LOGFIRE_CREDENTIALS_DIR=/app/.logfire

# Expose the default port
EXPOSE 8000

# Health check (API has health endpoint at /)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

# Run the API server
CMD ["leads-agent", "run", "--host", "0.0.0.0", "--port", "8000"]
