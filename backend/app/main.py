from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import answers, nouns, questions, tts, tutor
from app.api.deps import get_tutor_store
from app.api.request_guard import RequestGuardMiddleware
from app.runtime_settings import RuntimeSettings, load_runtime_settings


@asynccontextmanager
async def _initialize_store_on_startup(app: FastAPI) -> AsyncIterator[None]:
    """本番は起動時に DB を開き、権限不足や新しすぎる schema を起動失敗として見せる。"""
    store_factory = app.dependency_overrides.get(get_tutor_store, get_tutor_store)
    store_factory()
    yield


def create_app(settings: RuntimeSettings | None = None) -> FastAPI:
    settings = settings or load_runtime_settings()
    app = FastAPI(
        title="French Beginner API",
        version="0.1.0",
        lifespan=_initialize_store_on_startup if settings.is_production else None,
    )

    if settings.is_production:
        # 本番は nginx と同一オリジン。CORS は付けず、Host / Origin を検証する
        app.add_middleware(RequestGuardMiddleware, allowed_hosts=settings.allowed_hosts)
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(questions.router)
    app.include_router(answers.router)
    app.include_router(nouns.router)
    app.include_router(tts.router)
    app.include_router(tutor.router)
    app.add_api_route("/health", health, methods=["GET"])
    return app


def health() -> dict[str, str]:
    return {"status": "ok"}


app = create_app()
