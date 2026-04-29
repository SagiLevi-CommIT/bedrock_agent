# syntax=docker/dockerfile:1.7
# Build context must be the REPO ROOT.
# From the repo root run:  docker build -f app/Dockerfile -t agent:dev .

# ---- Stage 1: build the React/Vite SPA ----
FROM public.ecr.aws/docker/library/node:20-slim AS uibuild

ENV CI=1
WORKDIR /ui
COPY ui/package.json ./
RUN npm install --no-audit --no-fund
COPY ui/ ./
RUN npm run build

# ---- Stage 2: Python runtime that serves both /api and the SPA ----
FROM public.ecr.aws/docker/library/python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY app/pyproject.toml ./
COPY app/src ./src
COPY prompts ./prompts
COPY knowledge ./knowledge
COPY --from=uibuild /ui/dist ./ui_dist

RUN pip install --upgrade pip wheel && \
    pip install . && \
    chown -R 10001:10001 /app

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health').read()" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
