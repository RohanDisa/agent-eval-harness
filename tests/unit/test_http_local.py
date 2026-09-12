import pytest
from suites.customer_support.tools.http import HttpGet

from aeh.execution.http_fixtures import start_fixture_server
from aeh.execution.sandbox import Sandbox


@pytest.mark.local_http
@pytest.mark.asyncio
async def test_http_get_fixture_server(repo_root, tmp_path):
    server, _ = start_fixture_server(repo_root, port=8766)
    try:
        tool = HttpGet(allowlist_ports={8766})
        result = await tool.call({"url": "http://127.0.0.1:8766/products.json"}, Sandbox(tmp_path))
        assert result.ok
        assert "WDG-1" in result.output
    finally:
        server.shutdown()
