"""Application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.db import DATA, init_db, seed_sms_data
from app.handler import IntentExtractor, MessageHandler
from app.llm import create_model
from app.sms import HttpSmsGateway, SmsGateway
from app.webhook import router
from kb.retrieve import Retriever, SentenceEmbedder

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    gateway: SmsGateway | None = None,
    extractor: IntentExtractor | None = None,
    retriever: Retriever | None = None,
) -> FastAPI:
    config = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        init_db(config.db_path)
        seed_sms_data(config.db_path)
        retrieval = retriever
        if retrieval is None and config.embedding_model:
            retrieval = Retriever(
                DATA / "kb/kb_chunks.csv",
                SentenceEmbedder(config.embedding_model),
                DATA / "kb/vectors.npz",
            )
        logger.info("Retrieval enabled: %s", retrieval is not None)
        model = extractor if extractor is not None else create_model(config)
        application.state.message_handler = MessageHandler(
            config,
            gateway if gateway is not None else HttpSmsGateway(config),
            model,
            retriever=retrieval,
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
