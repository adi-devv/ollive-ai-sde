"""
Ingestion service — FastAPI application entry point.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import conversations_router, logs_router, messages_router
from .database import Base, engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


def create_tables() -> None:
    """Create all tables that do not yet exist (idempotent)."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created / verified OK")


def build_app() -> FastAPI:
    app = FastAPI(
        title="LLM Inference Logger — Ingestion Service",
        description=(
            "Receives inference logs from the LLMLogger SDK and exposes "
            "a query API for the chatbot UI."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — allow the Streamlit chatbot (and any other origin in dev)
    allowed_origins = os.environ.get(
        "CORS_ORIGINS", "*"
    ).split(",")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(logs_router)
    app.include_router(messages_router)
    app.include_router(conversations_router)

    @app.get("/", tags=["health"])
    def root() -> dict:
        return {"status": "ok", "service": "llm-inference-logger ingestion"}

    @app.get("/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok"}

    return app


# Create tables before the first request is handled
create_tables()

app = build_app()
