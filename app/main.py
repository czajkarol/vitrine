"""FastAPI application: wiring only.

Config is constructed here and injected downward. Nothing below reads the environment.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.providers.ai.factory import create_provider
from app.providers.aic.client import AicClient
from app.repositories.ai_usage import AiUsageRepository
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.database import Database
from app.repositories.history import HistoryRepository
from app.repositories.interpretations import NullSharedCache, SqliteInterpretationCache
from app.repositories.preferences import PreferencesRepository
from app.services.fallback import FallbackSet
from app.services.interpretation import InterpretationService
from app.services.selection import IIIF_BASE_KEY, SelectionService

logger = logging.getLogger(__name__)

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

    database = Database(settings.database_path)
    # Cheap when there is nothing to do, and it means a fresh clone boots into a working
    # database rather than erroring on the first query.
    await asyncio.to_thread(database.migrate)
    app.state.database = database

    preferences = PreferencesRepository(database)
    fallback = FallbackSet.load()
    index = ArtworkIndexRepository(database)

    # None when AI is not configured, which is the ordinary case and not a failure.
    provider = create_provider(settings)
    if provider is None:
        logger.info("AI is not configured; interpretation is unavailable.")
    else:
        logger.info("AI provider %s (%s) is available.", provider.name, provider.model)
    app.state.interpretation = InterpretationService(
        provider=provider,
        index=index,
        fallback=fallback,
        client=app.state.aic_client,
        settings=settings,
        local_cache=SqliteInterpretationCache(database),
        # Always empty, by decision rather than by omission. See ADR-0004.
        shared_cache=NullSharedCache(),
        usage=AiUsageRepository(database),
    )

    app.state.selection = SelectionService(
        index=index,
        history=HistoryRepository(database),
        preferences=preferences,
        fallback=fallback,
        client=app.state.aic_client,
    )
    # Seed the proxy's base from whatever we already know, so an index-only start can
    # still serve images without waiting for a live AIC response.
    app.state.iiif_base = await preferences.get(IIIF_BASE_KEY)

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
