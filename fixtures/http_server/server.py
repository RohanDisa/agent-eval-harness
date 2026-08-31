"""Static JSON fixture server bound to 127.0.0.1 only."""

from __future__ import annotations

import argparse
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_PORT = 8765


class FixtureHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return


def make_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    handler = partial(FixtureHandler, directory=str(DATA_DIR))
    return ThreadingHTTPServer((host, port), handler)


def serve_in_thread(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = make_server(host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    server = make_server(args.host, args.port)
    print(f"fixture server on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
