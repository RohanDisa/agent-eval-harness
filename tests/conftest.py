from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def block_httpx_send(monkeypatch, request):
    """CI and local tests have zero public network. Opt in with @pytest.mark.local_http."""
    if request.node.get_closest_marker("local_http") or request.node.get_closest_marker("network"):
        return

    async def blocked(self, request_, *args, **kwargs):  # noqa: ANN001
        raise RuntimeError(
            "network disabled in tests; mark the test local_http if the fixture server is required"
        )

    monkeypatch.setattr("httpx.AsyncClient.send", blocked)


@pytest.fixture
def repo_root() -> Path:
    return REPO


@pytest.fixture
def fixture_db(repo_root: Path) -> Path:
    from aeh.execution.runner import ensure_fixture_db

    return ensure_fixture_db(repo_root)
