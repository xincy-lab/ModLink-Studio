from __future__ import annotations

import argparse
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from modlink_core import ModLinkEngine, configure_host_logging

from .routes import DEFAULT_SSE_HEARTBEAT_INTERVAL_SECONDS, install_http_api

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings_path: str | Path | None = None,
    settings_version: int = 1,
    event_stream_maxsize: int = 1024,
    frame_stream_maxsize: int = 256,
    sse_heartbeat_interval_seconds: float = DEFAULT_SSE_HEARTBEAT_INTERVAL_SECONDS,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = ModLinkEngine(
            settings_path=settings_path,
            settings_version=settings_version,
        )
        app.state.engine = engine
        app.state.event_stream_maxsize = max(1, int(event_stream_maxsize))
        app.state.frame_stream_maxsize = max(1, int(frame_stream_maxsize))
        app.state.sse_heartbeat_interval_seconds = max(0.0, float(sse_heartbeat_interval_seconds))
        try:
            yield
        finally:
            engine.shutdown()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_http_api(app)
    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="modlink-server",
        description="Run the ModLink Studio HTTP server.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host interface to bind. Default: {DEFAULT_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to bind. Default: {DEFAULT_PORT}.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    log_path = configure_host_logging(log_filename="modlink-server.log")
    logger.info("Starting ModLink server on %s:%s", args.host, args.port)
    logger.info("Server logs will be written to %s", log_path)
    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        log_config=None,
    )
