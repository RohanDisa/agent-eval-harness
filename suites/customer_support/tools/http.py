from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from aeh.errors import AllowlistError
from aeh.execution.sandbox import Sandbox
from aeh.models import ToolResult

DEFAULT_ALLOWLIST_HOSTS = {"127.0.0.1", "localhost"}


class HttpGet:
    name = "http_get"
    schema: dict[str, Any] = {
        "name": "http_get",
        "description": "GET a JSON or text resource from the local fixture server.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    }

    def __init__(
        self,
        allowlist_hosts: set[str] | None = None,
        allowlist_ports: set[int] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.allowlist_hosts = allowlist_hosts or set(DEFAULT_ALLOWLIST_HOSTS)
        self.allowlist_ports = allowlist_ports
        self._client = client

    def check_url(self, url: str) -> None:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host not in self.allowlist_hosts:
            raise AllowlistError(f"host '{host}' is not on the HTTP allowlist")
        if parsed.scheme not in {"http", "https"}:
            raise AllowlistError(f"scheme '{parsed.scheme}' is not allowed")
        if self.allowlist_ports is not None:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if port not in self.allowlist_ports:
                raise AllowlistError(f"port {port} is not on the HTTP allowlist")

    async def call(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        _ = sandbox
        url = str(args.get("url", ""))
        try:
            self.check_url(url)
        except AllowlistError as exc:
            return ToolResult(ok=False, error=str(exc))
        client = self._client
        owns = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=10.0)
        try:
            response = await client.get(url)
            response.raise_for_status()
            return ToolResult(ok=True, output=response.text)
        except httpx.HTTPError as exc:
            return ToolResult(ok=False, error=f"http error: {exc}")
        finally:
            if owns:
                await client.aclose()
