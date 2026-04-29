# syntax=docker/dockerfile:1.7
# Build context must be the REPO ROOT, not app/.
# From the repo root run:  docker build -f app/Dockerfile -t agent:dev .

FROM public.ecr.aws/docker/library/python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY app/pyproject.toml ./
RUN pip install --upgrade pip wheel && \
    pip install --prefix=/install .

FROM public.ecr.aws/docker/library/python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/install/bin:$PATH \
    PYTHONPATH=/app

RUN groupadd -r app && useradd -r -g app -u 10001 -d /app app

COPY --from=builder /install /install
WORKDIR /app
COPY --chown=app:app app/src ./src
COPY --chown=app:app prompts ./prompts
COPY --chown=app:app knowledge ./knowledge

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health').read()" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
