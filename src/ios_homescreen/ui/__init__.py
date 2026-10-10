"""Browser UI: ``ios-homescreen ui`` serves an editor on 127.0.0.1 and opens it.

Starlette and uvicorn are imported only here, when the UI starts; the CLI and the
Python API do not need them. The page itself is plain JavaScript modules with a
vendored copy of Preact and htm (``static/vendor``), so there is no build step.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import socket
import tempfile
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..transport import Transport
from ..workflow import Timing

HOST = "127.0.0.1"


class UIUnavailable(RuntimeError):
    """The web dependencies are missing."""


@dataclass(frozen=True)
class Options:
    transport: Transport
    data_dir: Path
    backup_dir: Path
    timing: Timing
    port: int = 0
    open_browser: bool = True
    demo: bool = False


def _require() -> None:
    try:
        import starlette  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as exc:
        raise UIUnavailable(
            "the browser UI needs Starlette and uvicorn: "
            "pip install 'ios-homescreen[ui]' (or uv tool install, pipx install)"
        ) from exc


def _listen(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Lets a restart reuse the port while old connections linger in TIME_WAIT; it does
    # not allow two servers to listen on one port.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((HOST, port))
    except OSError:
        sock.close()
        raise
    sock.listen(64)
    sock.setblocking(False)
    return sock


def serve(options: Options, *, say: Callable[[str], None] = print) -> int:
    """Run the UI server until Ctrl+C. Returns an exit code."""
    _require()
    import uvicorn

    from .app import create_app
    from .demo import DemoDevice
    from .session import MemoryIcons, Session, Settings

    sock = _listen(options.port)
    port = sock.getsockname()[1]
    token = secrets.token_urlsafe(32)
    url = f"http://{HOST}:{port}/?token={token}"

    with contextlib.ExitStack() as stack:
        if options.demo:
            # Demo mode never touches the real data or cache directories.
            scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="ihs-demo-")))
            device = DemoDevice()

            async def opener(emit):  # type: ignore[no-untyped-def]
                return device

            session = Session(
                Settings(
                    data_dir=scratch,
                    backup_dir=scratch / "backups",
                    timing=Timing(read_timeout=10, verify_attempts=3, verify_interval=0.8),
                    demo=True,
                ),
                opener=opener,
                icons=MemoryIcons(),
            )
        else:
            session = Session(
                Settings(
                    data_dir=options.data_dir,
                    backup_dir=options.backup_dir,
                    timing=options.timing,
                    transport=options.transport,
                )
            )
        app = create_app(session, token=token, port=port)
        config = uvicorn.Config(
            app,
            log_level="warning",
            access_log=False,
            lifespan="on",
            proxy_headers=False,
            server_header=False,
            ws="none",
        )
        server = uvicorn.Server(config)

        async def main() -> None:
            running = asyncio.create_task(server.serve(sockets=[sock]))
            while not server.started and not running.done():
                await asyncio.sleep(0.05)
            if server.started:
                session.start_read()
                if options.demo:
                    say("ios-homescreen UI, demo mode: a pretend iPhone, no phone is contacted")
                else:
                    say("ios-homescreen UI")
                say(f"Open: {url}")
                say("The address works for this run only. Press Ctrl+C to stop.")
                if options.open_browser:
                    await asyncio.to_thread(webbrowser.open, url)
            await running

        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
        asyncio.run(main())
    return 0
