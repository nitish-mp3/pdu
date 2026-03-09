from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from schemas import CommandRequest, LockRequest, OverviewResponse
from service import service

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    service.initialize()
    task = asyncio.create_task(service.run())
    logger.info("PDU Outlet Guard started")
    try:
        yield
    finally:
        service.stop()
        await task
        logger.info("PDU Outlet Guard stopped")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        return response


app = FastAPI(
    title="PDU Outlet Guard",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(SecurityHeadersMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/overview", response_model=OverviewResponse)
def overview() -> dict:
    return service.overview()


@app.post("/api/devices/discover")
def discover(background_tasks: BackgroundTasks) -> dict:
    background_tasks.add_task(service.discover_devices)
    return {"ok": True, "message": "Discovery started in background."}


@app.post("/api/outlets/{outlet_id}/command")
def command(outlet_id: int, payload: CommandRequest) -> dict:
    result = service.issue_command(outlet_id, payload.action)
    if not result.accepted:
        raise HTTPException(status_code=409, detail=result.message)
    return {"ok": True, "message": result.message}


@app.post("/api/outlets/{outlet_id}/lock")
def lock(outlet_id: int, payload: LockRequest) -> dict:
    result = service.set_lock(outlet_id, payload.locked)
    if not result.accepted:
        raise HTTPException(status_code=404, detail=result.message)
    return {"ok": True, "message": result.message}


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
