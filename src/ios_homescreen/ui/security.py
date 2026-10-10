"""Keep other websites away from the local UI server.

The server listens on 127.0.0.1 only, but any page open in the same browser can still
send requests to it, and DNS rebinding can make a foreign page look same-origin. So:

* every response requires a session cookie, set from a random per-run token that is
  only in the URL printed in the terminal (``/?token=...``); the cookie is ``HttpOnly``
  and ``SameSite=Strict`` and the address bar loses the token after one redirect;
* the ``Host`` header must be ``127.0.0.1:PORT`` or ``localhost:PORT`` (DNS rebinding);
* ``Sec-Fetch-Site`` must be ``same-origin`` or ``none`` when the browser sends it;
* every API call except images (icons, wallpaper) also needs the token in an
  ``X-IHS-Token`` header,
  which only the served page knows (cross-origin pages cannot read it or set it without
  a CORS preflight that is never approved);
* requests that change something must carry an ``Origin`` equal to the server's own;
* responses forbid framing and cross-origin embedding (``Cross-Origin-Resource-Policy``).
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Awaitable, Callable, Iterable
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

TOKEN_HEADER = "x-ihs-token"
SAFE_METHODS = frozenset({"GET", "HEAD"})
ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})

_LOCKED_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ios-homescreen</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0f17;
color:#e6eaf2;font:16px/1.5 system-ui,sans-serif}}main{{max-width:30rem;padding:2rem}}
h1{{font-size:1.25rem}}code{{background:#1a2130;padding:.1rem .35rem;border-radius:.3rem}}
</style></head><body><main><h1>{title}</h1><p>{text}</p></main></body></html>
"""


def _is_image(path: str) -> bool:
    """Images are loaded by ``<img>``, which cannot send the token header."""
    return path.startswith("/api/icons/") or path == "/api/wallpaper"


def cookie_name(port: int) -> str:
    # Cookies ignore ports; the name keeps two servers on one machine apart.
    return f"ihs_{port}"


def same_token(given: str | None, token: str) -> bool:
    return isinstance(given, str) and hmac.compare_digest(given.encode(), token.encode())


def csp(script_hashes: Iterable[str] = ()) -> str:
    scripts = " ".join(["'self'", *(f"'sha256-{h}'" for h in script_hashes)])
    return (
        "default-src 'none'; "
        f"script-src {scripts}; "
        "style-src 'self'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "frame-ancestors 'none'"
    )


class Guard:
    """ASGI middleware that applies the rules in the module docstring."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        token: str,
        port: int,
        content_security_policy: str | None = None,
    ) -> None:
        self.app = app
        self.token = token
        self.port = port
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.cookie = cookie_name(port)
        self.csp = content_security_policy or csp()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        method = scope["method"]
        path = scope["path"]
        host = headers.get("host", "")

        if host not in self.hosts:
            await self._deny(send, "unknown_host", "This server only answers on 127.0.0.1.")
            return
        site = headers.get("sec-fetch-site")
        if site is not None and site not in ALLOWED_FETCH_SITES:
            await self._deny(send, "cross_site", "Requests from other sites are refused.")
            return
        if method not in SAFE_METHODS and headers.get("origin") != f"http://{host}":
            await self._deny(send, "bad_origin", "Requests from other origins are refused.")
            return

        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        if path == "/" and "token" in query:
            if same_token(query["token"][0], self.token):
                await self._enter(send)
            else:
                await self._locked(send)
            return

        if not same_token(self._cookie(headers), self.token):
            if path.startswith("/api/"):
                await self._deny(send, "no_session", "Open the address printed in the terminal.")
            else:
                await self._locked(send)
            return
        is_image = _is_image(path) and method in SAFE_METHODS
        if (
            path.startswith("/api/")
            and not is_image
            and not same_token(headers.get(TOKEN_HEADER), self.token)
        ):
            await self._deny(send, "no_token", "Missing or wrong request token.")
            return

        await self.app(scope, receive, self._secured(send, path))

    def _cookie(self, headers: dict[str, str]) -> str | None:
        jar: SimpleCookie = SimpleCookie()
        try:
            jar.load(headers.get("cookie", ""))
        except Exception:
            return None
        morsel = jar.get(self.cookie)
        return morsel.value if morsel else None

    def _headers(self, path: str) -> list[tuple[bytes, bytes]]:
        found = [
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"no-referrer"),
            (b"x-frame-options", b"DENY"),
            (b"cross-origin-opener-policy", b"same-origin"),
            (b"cross-origin-resource-policy", b"same-origin"),
            (b"content-security-policy", self.csp.encode()),
        ]
        if path.startswith("/api/") and not _is_image(path):
            found.append((b"cache-control", b"no-store"))
        return found

    def _secured(self, send: Send, path: str) -> Send:
        extra = self._headers(path)
        names = {name for name, _ in extra}

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in names]
                message = {**message, "headers": [*kept, *extra]}
            await send(message)

        return wrapped

    async def _enter(self, send: Send) -> None:
        cookie = f"{self.cookie}={self.token}; Path=/; HttpOnly; SameSite=Strict"
        await self._respond(
            send,
            303,
            b"",
            "text/plain; charset=utf-8",
            [(b"location", b"/"), (b"set-cookie", cookie.encode())],
        )

    async def _locked(self, send: Send) -> None:
        page = _LOCKED_PAGE.format(
            title="Open the link from the terminal",
            text="This page needs the address that <code>ios-homescreen editor</code> printed "
            "when it started. It contains a one-time key that changes on every start.",
        )
        await self._respond(send, 403, page.encode(), "text/html; charset=utf-8")

    async def _deny(self, send: Send, code: str, message: str) -> None:
        body = json.dumps({"code": code, "message": message}).encode()
        await self._respond(send, 403, body, "application/json")

    async def _respond(
        self,
        send: Send,
        status: int,
        body: bytes,
        content_type: str,
        extra: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        headers = [
            (b"content-type", content_type.encode()),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-store"),
            *self._headers("/"),
            *(extra or []),
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
