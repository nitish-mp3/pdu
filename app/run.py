"""Startup entrypoint with port wait-retry logic and logging setup."""
from __future__ import annotations

import logging
import os
import socket
import sys
import time
from pathlib import Path

PORT = 8023
HOST = "0.0.0.0"  # must be 0.0.0.0 so HA Supervisor ingress proxy can reach the container
PORT_WAIT_SECONDS = 20  # wait up to 20s for the previous add-on instance to release the port
DATA_DIR = Path(os.getenv("PDU_GUARD_DATA_DIR", "/data"))


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def _port_free(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False


def _wait_for_port(logger: logging.Logger) -> None:
    """Block until PORT is available or exit so HA shows a real failure."""
    if _port_free(HOST, PORT):
        return
    logger.warning(
        "Port %d is already in use (previous instance still shutting down). "
        "Waiting up to %ds...",
        PORT, PORT_WAIT_SECONDS,
    )
    deadline = time.monotonic() + PORT_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(1)
        if _port_free(HOST, PORT):
            logger.info("Port %d is now free.", PORT)
            return
    logger.error(
        "Port %d still in use after %ds. "
        "Cannot start — ingress_port in config.yaml must match the listening port. "
        "Exiting so HA shows a proper failure instead of silent 502.",
        PORT, PORT_WAIT_SECONDS,
    )
    sys.exit(1)


def main() -> None:
    _setup_logging()
    logger = logging.getLogger(__name__)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    _wait_for_port(logger)
    logger.info("Starting PDU Outlet Guard on %s:%d", HOST, PORT)

    try:
        import uvicorn

        uvicorn.run(
            "main:app",
            host=HOST,
            port=PORT,
            log_level="info",
            access_log=False,
        )
    except Exception:
        logger.exception("Fatal: uvicorn failed to start")
        sys.exit(1)


if __name__ == "__main__":
    main()
