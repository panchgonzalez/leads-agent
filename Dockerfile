FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (small set; add build deps only if you introduce packages that need compilation)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast installer) and project deps
RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
COPY main.py /app/main.py

RUN uv pip install --system -e .

EXPOSE 8000

CMD ["leads-agent", "run", "--host", "0.0.0.0", "--port", "8000"]