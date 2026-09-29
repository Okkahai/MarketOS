from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import ai, events, health, market, news, portfolio, system, trace
from app.core.config import APP_VERSION, get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title="MarketOS API",
        version=APP_VERSION,
        description="AI market research and paper trading. Simulation only: no real orders.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(ai.router)
    app.include_router(events.router)
    app.include_router(health.router)
    app.include_router(market.router)
    app.include_router(news.router)
    app.include_router(portfolio.router)
    app.include_router(system.router)
    app.include_router(trace.router)
    return app


app = create_app()
