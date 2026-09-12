import pytest
from suites.customer_support.tools.http import HttpGet

from aeh.errors import AllowlistError
from aeh.execution.sandbox import Sandbox
from aeh.models import ToolResult


def test_rejects_public_host():
    tool = HttpGet()
    with pytest.raises(AllowlistError):
        tool.check_url("https://example.com/x")


def test_rejects_bad_scheme():
    tool = HttpGet()
    with pytest.raises(AllowlistError):
        tool.check_url("file:///etc/passwd")


@pytest.mark.asyncio
async def test_call_returns_error_for_blocked_host(tmp_path):
    tool = HttpGet()
    result = await tool.call({"url": "https://evil.test/x"}, Sandbox(tmp_path))
    assert isinstance(result, ToolResult)
    assert result.ok is False
    assert "allowlist" in (result.error or "")


def test_port_allowlist():
    tool = HttpGet(allowlist_ports={8765})
    with pytest.raises(AllowlistError):
        tool.check_url("http://127.0.0.1:80/x")
    tool.check_url("http://127.0.0.1:8765/x")
