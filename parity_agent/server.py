"""Serve the bundled demo sites from background threads (one origin per platform)."""
from __future__ import annotations

import contextlib
import functools
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import DEMO_SITES_DIR


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        return


@contextlib.contextmanager
def serve_directory(directory: Path) -> Iterator[str]:
    """Serve ``directory`` on an ephemeral localhost port; yields the base URL."""
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@contextlib.contextmanager
def serve_demo_sites() -> Iterator[tuple[str, str]]:
    """Serve demo_sites/web and demo_sites/app on two separate origins; yields (web_url, app_url)."""
    with serve_directory(DEMO_SITES_DIR / "web") as web, serve_directory(DEMO_SITES_DIR / "app") as app:
        yield f"{web}/index.html", f"{app}/index.html"
