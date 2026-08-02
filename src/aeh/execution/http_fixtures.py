from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from aeh.paths import REPO_ROOT

DEFAULT_PORT = 8765


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return


def start_fixture_server(
    repo_root: Path | None = None,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    data = (repo_root or REPO_ROOT) / "fixtures" / "http_server" / "data"
    handler = partial(_Quiet, directory=str(data))
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
