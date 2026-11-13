"""The desktop app: the browser editor in its own window, without a terminal.

It runs the same server as ``ios-homescreen editor`` on a free local port, in a
background thread, and shows the page in a pywebview window (WebKit on macOS, WebView2
on Windows, Qt on Linux). Closing the window stops the server. Nobody picks USB or
Wi-Fi here, so the app tries USB first and the network when no cable is in.
"""

from __future__ import annotations

import html
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .paths import BACKUPS, data_dir
from .transport import Transport
from .ui import Options, serve
from .workflow import Timing

TITLE = "ios-homescreen"
START_TIMEOUT = 30.0
# The window icon on Linux; macOS and Windows take it from the app bundle.
ICON = Path(__file__).parent / "ui" / "static" / "logo.png"


def _options(demo: bool) -> Options:
    data = data_dir()
    return Options(
        transport=Transport(),
        data_dir=data,
        backup_dir=data / BACKUPS,
        timing=Timing(),
        open_browser=False,
        demo=demo,
        auto=True,
    )


def _self_test() -> int:
    """For the build pipeline: start the server in demo mode, load the page, stop.

    It also imports the window backend, so a package that lost it fails here.
    """
    import http.cookiejar
    import urllib.request

    import webview  # noqa: F401

    started = threading.Event()
    found: dict[str, object] = {}

    def on_started(url: str, stop: Callable[[], None]) -> None:
        found["url"], found["stop"] = url, stop
        started.set()

    thread = threading.Thread(
        target=serve,
        args=(_options(demo=True),),
        kwargs={"say": lambda _text: None, "on_started": on_started},
        daemon=True,
    )
    thread.start()
    if not started.wait(START_TIMEOUT):
        print("self-test: the editor did not start")
        return 1
    # The address carries a one-time token that the server swaps for a cookie.
    browser = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    with browser.open(str(found["url"]), timeout=10) as page:
        ok = page.status == 200 and b"ios-homescreen" in page.read()
    stop = found["stop"]
    assert callable(stop)
    stop()
    thread.join(timeout=10)
    print(f"self-test: {'ok' if ok else 'the page did not load'} ({__version__})")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--self-test" in args:
        return _self_test()

    import webview

    started = threading.Event()
    found: dict[str, object] = {}

    def on_started(url: str, stop: Callable[[], None]) -> None:
        found["url"], found["stop"] = url, stop
        started.set()

    def run() -> None:
        try:
            serve(_options("--demo" in args), say=lambda _text: None, on_started=on_started)
        except BaseException as exc:  # shown in the window instead of a lost traceback
            found["error"] = exc
            started.set()

    server = threading.Thread(target=run, name="ios-homescreen-server", daemon=True)
    server.start()
    if not started.wait(START_TIMEOUT) or "error" in found:
        message = str(found.get("error") or "the editor did not start")
        page = f"<p>ios-homescreen could not start: {html.escape(message)}</p>"
        webview.create_window(TITLE, html=page)
        webview.start()
        return 1

    webview.create_window(
        f"{TITLE} {__version__}",
        str(found["url"]),
        width=1280,
        height=820,
        min_size=(900, 600),
    )
    try:
        webview.start(icon=str(ICON))
    finally:
        stop = found["stop"]
        assert callable(stop)
        stop()
        server.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
