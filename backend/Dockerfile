# ベースイメージは版と digest で固定する。更新手順は docs/operations/local-lan-runbook.md。
FROM ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 AS uv

# Debian 13 へ移行して bookworm の util-linux / perl の既知脆弱性を解消する。
FROM python:3.12.16-slim-trixie@sha256:8523d6abeb48ceae0b7240d30c5808fc26cb79c1a635bacdf19cf3baecfbec07 AS base
WORKDIR /app

COPY --from=uv /uv /usr/local/bin/uv

# 依存は uv.lock どおりに /opt/venv へ入れる。dev の bind mount（/app）で隠れない
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml uv.lock ./

FROM base AS dev
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
# dev dependency group（pytest / ruff など）を含める
RUN uv sync --locked --no-install-project --group dev
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS prod
ARG APP_COMMIT
ARG APP_DIRTY=false
LABEL org.opencontainers.image.revision=$APP_COMMIT
ENV APP_COMMIT=$APP_COMMIT APP_DIRTY=$APP_DIRTY
RUN UV_COMPILE_BYTECODE=1 uv sync --locked --no-install-project --no-dev \
    && rm /usr/local/bin/uv \
    && groupadd --system --gid 10001 tutor \
    && useradd --system --uid 10001 --gid tutor --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin tutor \
    && install -d -o tutor -g tutor -m 0700 /var/lib/french-tutor /var/cache/french-tutor
# コードは root 所有のまま。実行ユーザーが書けるのは DB と TTS cache の volume、/tmp だけ
COPY app ./app
RUN python -m compileall -q app
ENV APP_ENV=production \
    TUTOR_DATA_DIR=/var/lib/french-tutor \
    TTS_CACHE_DIR=/var/cache/french-tutor/tts
USER tutor:tutor
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -m app.persistence.readiness --quiet \
        && python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
# SQLite と起動時 upgrade を1プロセスに保つため worker は1つ
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header"]
