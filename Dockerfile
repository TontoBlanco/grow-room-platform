# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Slim still has zlib1g 1:1.3.dfsg+really1.3.1-1+b1. Debian security already
# published 1:1.3.dfsg+really1.3.1-1+deb13u1 (DSA-6613-1) for CVE-2026-76844
# and CVE-2026-85091. Leave the version unpinned so the next security upload
# replaces it. Package lists are removed so they are not baked into the image.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --only-upgrade zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so this layer caches between code changes
COPY pyproject.toml README.md ./
COPY sensor_service ./sensor_service
# postgres extra lets AUDIT_DATABASE_URL work. SQLite stays the default when
# that variable is unset, including the k3d chart.
RUN pip install ".[postgres]" && useradd --create-home --uid 10001 appuser

USER appuser
EXPOSE 8000

# python:slim has no curl, so use Python for the healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

CMD ["uvicorn", "sensor_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
