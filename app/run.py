"""Startup entrypoint with port fallback and logging setup."""
from __future__ import annotations

import logging
import os
import socket
import sys
from pathlib import Path

DEFAULT_PORT = 8023
FALLBACK_PORTS = [8024, 8025, 8026, 8080, 9000]
HOST = "0.0.0.0"  # must be 0.0.0.0 so HA Supervisor ingress proxy can reach the container
DATA_DIR = Path(os.getenv("PDU_GUARD_DATA_DIR", "/data"))


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def _port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
        return True
    except OSError:
        return False


def _pick_port() -> int:
    if _port_available(HOST, DEFAULT_PORT):
        return DEFAULT_PORT
    logger = logging.getLogger(__name__)
    logger.warning("Port %d is in use, trying fallbacks", DEFAULT_PORT)
    for port in FALLBACK_PORTS:
        if _port_available(HOST, port):
            logger.info("Using fallback port %d", port)
            return port
    logger.error("No available port found; falling back to %d anyway", DEFAULT_PORT)
    return DEFAULT_PORT


def main() -> None:
    _setup_logging()
    logger = logging.getLogger(__name__)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    port = _pick_port()
    logger.info("Starting PDU Outlet Guard on %s:%d", HOST, port)

    try:
        import uvicorn  # noqa: delayed import after logging is configured

        uvicorn.run(
            "main:app",
            host=HOST,
            port=port,
            log_level="info",
            access_log=False,
        )
    except Exception:
        logger.exception("Fatal: uvicorn failed to start")
        sys.exit(1)


if __name__ == "__main__":
    main()
