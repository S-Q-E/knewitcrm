# Single Railway image: Node builds the SPA, Python serves API + static.
# Base images are pinned by digest (version tags shown for readability).
# Refresh: docker buildx imagetools inspect python:3.12-slim / node:20-slim,
# then update the digests below (see docs/DEPLOY.md).
ARG PYTHON_IMAGE=python:3.12.14-slim@sha256:44ff437bba879d4941b710a369a8f19266aea34b29002807f0c487fabc9eec9b
ARG NODE_IMAGE=node:20.19.0-slim@sha256:8898f8ed3c0126667837b678979b4ed83306c856a1227c8bf5f5f77740c25cd6

FROM ${NODE_IMAGE} AS frontend-build

WORKDIR /app/frontend

# Dependency layer first so rebuilds reuse the npm cache.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependency layer first so rebuilds reuse the pip cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY scripts ./scripts
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN useradd --system --no-create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8000') + '/api/health')"

# Railway passes $PORT automatically. The entrypoint migrates first
# (concurrent-safe via advisory lock), then starts uvicorn with 2 workers;
# --proxy-headers trusts Railway's X-Forwarded-For (client IP resolution is
# still gated by TRUSTED_PROXY_HOPS). --timeout-graceful-shutdown gives
# in-process workers time to finish a cycle.
CMD ["./scripts/docker-entrypoint.sh"]
