"""
Application entry point for the AI analyst backend.

This module instantiates the FastAPI app and includes all API
routers. It also provides a root path description for the API.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import router as api_router
from .startup import print_startup_diagnostics


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """FastAPI lifespan handler: runs startup diagnostics, then yields."""
    print_startup_diagnostics()
    yield
    # Shutdown: nothing to clean up currently.


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AI Analyst Backend",
        version="0.1.0",
        description="Backend service for an AI‑powered company analysis platform",
        lifespan=lifespan,
    )
    app.include_router(api_router)
    return app


app = create_app()
