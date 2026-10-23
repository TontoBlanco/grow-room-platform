# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so this layer caches between code changes
COPY pyproject.toml README.md ./
COPY sensor_service ./sensor_service
RUN pip install . && useradd --create-home --uid 10001 appuser

USER appuser
EXPOSE 8000

# python:slim has no curl, so use Python for the healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

CMD ["uvicorn", "sensor_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
