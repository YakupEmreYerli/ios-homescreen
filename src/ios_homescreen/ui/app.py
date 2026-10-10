"""The HTTP API and static files of the browser UI (Starlette).

Endpoints (all under the guard in :mod:`.security`):

========================  ======  ===================================================
``/``                     GET     The editor page (``?token=`` once, then a cookie)
``/static/...``           GET     Scripts, styles and vendored libraries
``/api/state``            GET     Device, connection, last read (as a view), job, icons
``/api/read``             POST    Start reading the phone (a job)
``/api/plan``             POST    Check an edited layout: issues, changes, summary
``/api/apply``            POST    Plan and start the safe write (a job)
``/api/job``              GET     The current job; ``?since=N`` skips known events
``/api/job/events``       GET     The current job's events as a stream (NDJSON)
``/api/backups``          GET     Backups, newest first
``/api/backups/restore``  POST    Start restoring a backup (a job)
``/api/export``           POST    The edited layout as a TOML file
``/api/import``           POST    A TOML layout file as an editable view
``/api/icons``            GET     Which icons are available, and whether more are coming
``/api/icons/{id}``       GET     One icon image
========================  ======  ===================================================
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from ..planner import LayoutError
from ..state import StateError
from .errors import friendly
from .security import Guard, csp
from .session import Busy, LayoutProblems, NoRead, Session

STATIC = Path(__file__).parent / "static"
MAX_BODY = 4 * 1024 * 1024
_ICON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_IMPORT_MAP = re.compile(r'<script type="importmap">(.*?)</script>', re.S)
_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
}


def _static_files() -> dict[str, Path]:
    return {
        path.relative_to(STATIC).as_posix(): path
        for path in STATIC.rglob("*")
        if path.is_file() and path.suffix in _TYPES and path.name != "index.html"
    }


def _error(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"code": code, "message": message, **extra}, status_code=status)


async def _body(request: Request) -> dict[str, Any]:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise ValueError("expected application/json")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise ValueError("request body too large")
        chunks.append(chunk)
    data = json.loads(b"".join(chunks) or b"{}")
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def _layout(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    layout = data.get("layout")
    if not isinstance(layout, dict):
        raise ValueError("layout must be an object with dock and pages")
    remove = data.get("remove", [])
    if not isinstance(remove, list) or not all(isinstance(x, str) for x in remove):
        raise ValueError("remove must be a list of ids")
    return layout, remove


def _handle(exc: Exception) -> Response:
    if isinstance(exc, LayoutProblems):
        return _error(422, "layout_invalid", str(exc), issues=exc.issues)
    if isinstance(exc, LayoutError):
        return _error(422, "layout_invalid", str(exc), issues=exc.to_dict()["issues"])
    if isinstance(exc, Busy):
        return _error(409, "busy", str(exc))
    if isinstance(exc, NoRead):
        return _error(409, "no_read", str(exc))
    if isinstance(exc, StateError):
        return _error(400, "invalid", str(exc))
    if isinstance(exc, ValueError):
        return _error(400, "bad_request", str(exc))
    return _error(500, "unexpected", str(exc), error=friendly(exc))


def create_app(session: Session, *, token: str, port: int) -> Any:
    """The ASGI app: Starlette routes behind the :class:`~.security.Guard`."""
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    hashes = [
        base64.b64encode(hashlib.sha256(m.group(1).encode()).digest()).decode()
        for m in _IMPORT_MAP.finditer(page)
    ]
    policy = csp(hashes)
    files = _static_files()

    async def index(request: Request) -> Response:
        html = page.replace("{{TOKEN}}", token)
        return Response(html, media_type="text/html", headers={"cache-control": "no-store"})

    async def static(request: Request) -> Response:
        path = files.get(request.path_params["path"])
        if path is None:
            return Response("Not found", status_code=404, media_type="text/plain")
        return Response(
            path.read_bytes(),
            media_type=_TYPES[path.suffix],
            headers={"cache-control": "no-cache"},
        )

    async def state(request: Request) -> Response:
        return JSONResponse(session.state())

    async def read(request: Request) -> Response:
        try:
            job = session.start_read()
        except Exception as exc:
            return _handle(exc)
        return JSONResponse({"job": job.to_dict()}, status_code=202)

    async def plan(request: Request) -> Response:
        try:
            layout, remove = _layout(await _body(request))
            return JSONResponse(session.check(layout, remove))
        except Exception as exc:
            return _handle(exc)

    async def apply(request: Request) -> Response:
        try:
            data = await _body(request)
            layout, remove = _layout(data)
            job = session.start_apply(layout, remove, force=bool(data.get("force", False)))
        except Exception as exc:
            return _handle(exc)
        return JSONResponse({"job": job.to_dict()}, status_code=202)

    def _since(request: Request) -> int:
        try:
            return max(0, int(request.query_params.get("since", "0")))
        except ValueError:
            return 0

    async def job(request: Request) -> Response:
        current = session.job
        return JSONResponse({"job": current.to_dict(_since(request)) if current else None})

    async def job_events(request: Request) -> Response:
        current = session.job
        if current is None:
            return _error(404, "no_job", "nothing has run yet")
        since = _since(request)

        async def lines() -> AsyncIterator[bytes]:
            seen = since
            while True:
                wake = current.waiter()
                for event in current.events[seen:]:
                    seen += 1
                    yield (json.dumps({"seq": seen, "event": event}) + "\n").encode()
                if not current.running:
                    yield (json.dumps({"done": True, "job": current.to_dict(seen)}) + "\n").encode()
                    return
                await wake.wait()

        return StreamingResponse(lines(), media_type="application/x-ndjson")

    async def backups(request: Request) -> Response:
        return JSONResponse({"backups": session.backups(), "directory": "backups"})

    async def restore(request: Request) -> Response:
        try:
            data = await _body(request)
            job = session.start_restore(str(data.get("name", "")))
        except Exception as exc:
            return _handle(exc)
        return JSONResponse({"job": job.to_dict()}, status_code=202)

    async def export(request: Request) -> Response:
        try:
            layout, remove = _layout(await _body(request))
            return JSONResponse({"toml": session.export(layout, remove)})
        except Exception as exc:
            return _handle(exc)

    async def import_(request: Request) -> Response:
        try:
            data = await _body(request)
            text = data.get("toml")
            if not isinstance(text, str):
                raise ValueError("toml must be a string")
            return JSONResponse(session.import_layout(text))
        except Exception as exc:
            return _handle(exc)

    async def icons(request: Request) -> Response:
        return JSONResponse(session.icon_state())

    async def icon(request: Request) -> Response:
        ident = request.path_params["ident"]
        found = session.icon(ident) if _ICON_ID.match(ident) else None
        if found is None:
            return Response(status_code=404)
        data, media_type = found
        # Revalidate every time (icons change when apps update); the ETag keeps it cheap.
        etag = '"' + hashlib.sha256(data).hexdigest()[:32] + '"'
        headers = {"cache-control": "private, no-cache", "etag": etag}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(data, media_type=media_type, headers=headers)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        yield
        await session.shutdown()

    routes = [
        Route("/", index, methods=["GET"]),
        Route("/static/{path:path}", static, methods=["GET"]),
        Route("/api/state", state, methods=["GET"]),
        Route("/api/read", read, methods=["POST"]),
        Route("/api/plan", plan, methods=["POST"]),
        Route("/api/apply", apply, methods=["POST"]),
        Route("/api/job", job, methods=["GET"]),
        Route("/api/job/events", job_events, methods=["GET"]),
        Route("/api/backups", backups, methods=["GET"]),
        Route("/api/backups/restore", restore, methods=["POST"]),
        Route("/api/export", export, methods=["POST"]),
        Route("/api/import", import_, methods=["POST"]),
        Route("/api/icons", icons, methods=["GET"]),
        Route("/api/icons/{ident}", icon, methods=["GET"]),
    ]
    return Starlette(
        routes=routes,
        middleware=[Middleware(Guard, token=token, port=port, content_security_policy=policy)],
        lifespan=lifespan,
    )
