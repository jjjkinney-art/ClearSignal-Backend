"""
Application entry point for the AI analyst backend.

This module instantiates the FastAPI app and includes all API
routers. It also provides a root path description for the API.
"""

from fastapi import FastAPI

from .api import router as api_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AI Analyst Backend",
        version="0.1.0",
        description="Backend service for an AI‑powered company analysis platform",
    )
    app.include_router(api_router)
    return app


app = create_app()
