"""FastAPI application: wiring only.

Config is constructed here and injected downward. Nothing below reads the environment.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.providers.aic.client import AicClient

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    app.state.aic_client = AicClient(settings)
    # Learned from the first AIC response; the image proxy reads it from here rather than
    # accepting a base URL from the caller.
    app.state.iiif_base = None
    try:
        yield
    finally:
        await app.state.aic_client.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="vitrine",
        description="Ambient display for public-domain artworks from the Art Institute of Chicago",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings or get_settings()
    app.include_router(router)
    if FRONTEND_DIR.is_dir():
        # Mounted last so it cannot shadow /api.
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
