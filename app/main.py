"""FastAPI application: wiring only.

Config is constructed here and injected downward. Nothing below reads the environment.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles

from app.api.errors import validation_error_handler
from app.api.middleware import request_id_middleware
from app.api.routes import router
from app.core.config import DEFAULT_AIC_USER_AGENT, Settings, get_settings
from app.core.logging import configure as configure_logging
from app.providers.ai.factory import create_provider
from app.providers.aic.client import AicClient
from app.repositories.ai_usage import AiUsageRepository
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.credentials import create_credential_store
from app.repositories.database import Database
from app.repositories.history import HistoryRepository
from app.repositories.interpretations import NullSharedCache, SqliteInterpretationCache
from app.repositories.preferences import PreferencesRepository
from app.services.ai_credentials import AiCredentialService
from app.services.fallback import FallbackSet
from app.services.interpretation import InterpretationService
from app.services.selection import IIIF_BASE_KEY, SelectionService

logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level, settings.log_format)
    if settings.aic_user_agent == DEFAULT_AIC_USER_AGENT:
        # A warning and not a failure: the app still works, and refusing to start over a
        # courtesy header would be a worse first five minutes than a log line. But AIC asks
        # for a contact address on every request and the placeholder is not one, so this
        # says so once, at the only moment anyone is looking at the terminal.
        logger.warning(
            "AIC_USER_AGENT is still the placeholder %r. AIC asks every client to identify "
            "itself with a project name and a contact address; set AIC_USER_AGENT in .env.",
            DEFAULT_AIC_USER_AGENT,
        )
    # Monotonic, so /api/stats reports how long this process has been up rather than
    # something a clock change can make negative.
    app.state.started_at = time.monotonic()
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

    # A key pasted into the settings panel outranks .env and is applied here, before
    # the first request. Everything about it degrades to "AI is off" rather than to a
    # failed boot — see the service.
    app.state.ai_credentials = AiCredentialService(
        settings=settings,
        credentials=create_credential_store(database),
        preferences=preferences,
        interpretation=app.state.interpretation,
        env_provider=provider,
    )
    await app.state.ai_credentials.restore()

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
        # Whichever provider is live by now — the one built from .env, or one built from
        # a key saved while the app was running. A real provider holds an HTTP client of
        # its own; the mock does not.
        await app.state.ai_credentials.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="vitrine",
        description="Ambient display for public-domain artworks from the Art Institute of Chicago",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings or get_settings()
    # Before the routes, because one of them takes an API key and the default 422 would
    # echo it back. See app/api/errors.py.
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    # Outermost, so the id exists for anything below it — including the exception handler.
    app.middleware("http")(request_id_middleware)
    app.include_router(router)
    if FRONTEND_DIR.is_dir():
        # Mounted last so it cannot shadow /api.
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
