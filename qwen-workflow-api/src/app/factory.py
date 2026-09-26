from __future__ import annotations

from fastapi import FastAPI

from routes import accounts, chat, health, images, jobs, videos, worker_api


def create_app() -> FastAPI:
    app = FastAPI(
        title="Qwen Workflow API",
        version="0.1.0",
        description=(
            "OpenAI-compatible control plane for Qwen CLI workers. "
            "Jobs are async; poll /v1/jobs/{id}. Continuity via chat_id + bound account_id."
        ),
    )
    app.include_router(health.router)
    app.include_router(accounts.router)
    app.include_router(chat.router)
    app.include_router(images.router)
    app.include_router(videos.router)
    app.include_router(jobs.router)
    app.include_router(worker_api.router)
    return app
