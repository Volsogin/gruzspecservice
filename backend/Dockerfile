# syntax=docker/dockerfile:1
# Build context: the repository root (see docker-compose.yml) — the image contains the API and the built site.

# --- 1. frontend: Vite build → /web/dist ---------------------------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. backend: FastAPI serves /api, /admin, /media and the SPA from the same origin -------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Non-root user; UID/GID are build args so they can match the host user.
ARG UID=1000
ARG GID=1000
RUN groupadd -g "${GID}" app && useradd -u "${UID}" -g app -m -s /usr/sbin/nologin app \
    && pip install --no-cache-dir uv==0.13.9

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
COPY --from=web /web/dist /app/web
# Writable data lives outside the source tree; the named volume `appdata` is mounted at /data.
RUN mkdir -p /data/media /data/mail && chown -R app:app /data
USER app

ENV MEDIA_DIR=/data/media MAIL_DUMP_DIR=/data/mail FRONTEND_DIST_DIR=/app/web
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
