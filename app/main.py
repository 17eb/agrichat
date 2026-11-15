"""Application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.db import init_db


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        init_db(config.db_path)
        yield

    application = FastAPI(title="AgriChat", lifespan=lifespan)
    application.state.settings = config

    @application.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    return application


app = create_app()
