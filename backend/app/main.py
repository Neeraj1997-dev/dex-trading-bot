"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.api.routes.api import router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.mongodb import bootstrap_data, close_db, connect_db
from app.services.container import build_container
from app.workers.scheduler import BotScheduler

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    await connect_db(settings)
    await bootstrap_data(settings)
    container = build_container(settings)
    app.state.container = container
    scheduler = BotScheduler(container)
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "app_started",
        mode=settings.trading_mode,
        dex=settings.dex_provider,
        env=settings.environment,
    )
    yield
    scheduler.shutdown()
    await close_db()
    logger.info("app_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "Automated DEX Trading Platform — AI analysis with deterministic risk controls. "
            "Private keys and API secrets never leave the backend."
        ),
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
