"""Application entry point."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.db import DATA, init_db, seed_sms_data
from app.handler import IntentExtractor, MessageHandler
from app.llm import create_model
from app.sms import HttpSmsGateway, SmsGateway
from app.webhook import router
from kb.retrieve import Retriever, SentenceEmbedder
from web.admin import add_admin_headers
from web.admin import guarded as admin_guarded_router
from web.admin import router as admin_router
from web.auth import LOGIN_LIMIT, LOGIN_WINDOW_SECONDS
from web.public import SIMULATE_LIMIT, SIMULATE_WINDOW_SECONDS, STATIC, SimulatorGateway
from web.public import router as public_router
from web.ratelimit import RateLimiter

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
        application.state.simulator_handler = MessageHandler(
            config, SimulatorGateway(), model, retriever=retrieval
        )
        yield

    application = FastAPI(title="AgriChat", lifespan=lifespan)
    application.state.settings = config
    application.state.simulate_limiter = RateLimiter(SIMULATE_LIMIT, SIMULATE_WINDOW_SECONDS)
    application.state.login_limiter = RateLimiter(LOGIN_LIMIT, LOGIN_WINDOW_SECONDS)
    application.include_router(router)
    application.include_router(public_router)
    application.include_router(admin_router)
    application.include_router(admin_guarded_router)
    application.mount("/static", StaticFiles(directory=STATIC), name="static")

    @application.middleware("http")
    async def admin_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        add_admin_headers(response, request.url.path)
        return response

    @application.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    return application


app = create_app()
