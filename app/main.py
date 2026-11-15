"""Application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.db import init_db, seed_sms_data
from app.handler import IntentExtractor, MessageHandler
from app.sms import HttpSmsGateway, SmsGateway
from app.webhook import router


def create_app(
    settings: Settings | None = None,
    gateway: SmsGateway | None = None,
    extractor: IntentExtractor | None = None,
) -> FastAPI:
    config = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        init_db(config.db_path)
        seed_sms_data(config.db_path)
        application.state.message_handler = MessageHandler(
            config, gateway if gateway is not None else HttpSmsGateway(config), extractor
        )
        yield

    application = FastAPI(title="AgriChat", lifespan=lifespan)
    application.state.settings = config
    application.include_router(router)

    @application.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    return application


app = create_app()
