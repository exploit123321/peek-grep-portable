"""Main FastAPI application: API, static frontend, indexer status, and window controls."""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import APP_VERSION, DATA_DIR, DB_PATH, PROJECT_ROOT
from app.indexer.db import count_files, count_fts_indexed
from app.routers import actions, folders, preview, search
from app.schemas import ActionResponse, ResizeWindowRequest, StatusResponse, WindowSizeResponse
from app.state import desktop_hooks, index_manager, settings_store

# Pages from the app's own origin only: no inline scripts, so injected HTML cannot run code
PAGE_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; frame-src 'self'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'"
)

def _set_hook(name: str) -> Callable[[Callable], None]:
    def setter(cb: Callable) -> None:
        desktop_hooks[name] = cb
    return setter

# Registration functions used by desktop_app (and the tests)
set_hide_window_callback = _set_hook("hide")
set_show_window_callback = _set_hook("show")
set_resize_window_callback = _set_hook("resize")
set_toggle_maximize_callback = _set_hook("toggle_maximize")
set_get_window_size_callback = _set_hook("window_size")
set_pick_folders_callback = _set_hook("pick_folders")
set_open_data_folder_callback = _set_hook("open_data_folder")
set_quit_callback = _set_hook("quit")

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager. Indexing starts only when working folders exist."""
    print("[Startup] Opening index and settings...")
    await run_in_threadpool(index_manager.start)
    yield
    print("[Shutdown] Stopping workers...")
    index_manager.stop()


app = FastAPI(
    title="Peek & Grep Portable API",
    description="Folder-scoped desktop search & Quick Look engine",
    version=APP_VERSION,
    lifespan=lifespan,
)

# Only local host names (blocks DNS rebinding). No CORS: other web pages cannot read this API.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers.setdefault("Content-Security-Policy", PAGE_CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response

# Register routers
app.include_router(search.router)
app.include_router(preview.router)
app.include_router(actions.router)
app.include_router(folders.router)

@app.get("/api/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """General backend status."""
    return StatusResponse(
        status="operational",
        version=APP_VERSION,
        indexed_files=await run_in_threadpool(count_files),
        content_indexed=await run_in_threadpool(count_fts_indexed),
        setup_done=settings_store.setup_done,
        folders=settings_store.folders(),
        data_dir=str(DATA_DIR),
        db_path=DB_PATH,
    )

@app.get("/api/indexer/status")
async def get_indexer_status() -> dict:
    """Live scan and content-reading progress, per working folder."""
    return await run_in_threadpool(index_manager.status)

def _call_hook(name: str, *args, ok: str = "Done") -> ActionResponse:
    hook = desktop_hooks.get(name)
    if hook is None:
        return ActionResponse(success=True, message="No native desktop window active")
    try:
        result = hook(*args)
        return ActionResponse(success=True, message=f"{ok}: {result}" if result is not None else ok)
    except Exception as e:
        return ActionResponse(success=False, message=str(e))

@app.post("/api/actions/hide-window", response_model=ActionResponse)
async def hide_desktop_window() -> ActionResponse:
    """Hide native desktop window to the tray."""
    return _call_hook("hide", ok="Window hidden")

@app.post("/api/actions/show-window", response_model=ActionResponse)
async def show_desktop_window() -> ActionResponse:
    """Show and focus the desktop window (used by a second app start)."""
    return _call_hook("show", ok="Window shown")

@app.post("/api/actions/resize-window", response_model=ActionResponse)
async def resize_desktop_window(payload: ResizeWindowRequest) -> ActionResponse:
    """Resize native desktop window."""
    return _call_hook("resize", payload.width, payload.height, ok=f"Resized to {payload.width}x{payload.height}")

@app.post("/api/actions/toggle-maximize", response_model=ActionResponse)
async def toggle_maximize_desktop_window() -> ActionResponse:
    """Toggle maximize for native desktop window."""
    return _call_hook("toggle_maximize", ok="Window maximize toggled")

@app.post("/api/actions/open-data-folder", response_model=ActionResponse)
async def open_data_folder() -> ActionResponse:
    """Open the portable data folder in Explorer."""
    return _call_hook("open_data_folder", ok="Opened data folder")

@app.get("/api/actions/window-size", response_model=WindowSizeResponse)
async def get_desktop_window_size() -> WindowSizeResponse:
    """Get current window size and maximized state."""
    hook = desktop_hooks.get("window_size")
    if hook:
        try:
            return WindowSizeResponse(**hook())
        except Exception:
            pass
    return WindowSizeResponse(width=880, height=620, is_maximized=False)


# Serve production frontend if built
dist_dir = os.path.join(PROJECT_ROOT, "frontend", "dist")
if os.path.exists(dist_dir) and os.path.isdir(dist_dir):
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")
