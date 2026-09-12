import sys
from pathlib import Path

import pytest

from aeh.errors import SandboxEscapeError
from aeh.execution.sandbox import Sandbox


def test_relative_escape_rejected(tmp_path: Path):
    box = Sandbox(tmp_path)
    with pytest.raises(SandboxEscapeError):
        box.resolve_path("../../etc/passwd")


def test_absolute_escape_rejected(tmp_path: Path):
    box = Sandbox(tmp_path)
    with pytest.raises(SandboxEscapeError):
        box.resolve_path(str(Path("/etc/passwd")))


def test_write_and_list_inside(tmp_path: Path):
    box = Sandbox(tmp_path)
    box.write_text("a/b.txt", "hi")
    assert box.read_text("a/b.txt") == "hi"
    assert "a/b.txt" in box.list_files(".")
    snap = box.snapshot()
    assert snap["files"]["a/b.txt"]["text"] == "hi"


def test_cleanup_deletes_owned_temp():
    box = Sandbox()
    root = box.root
    box.write_text("x.txt", "1")
    box.cleanup()
    assert not root.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="symlink privileges often missing on Windows")
def test_symlink_escape_rejected(tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    box = Sandbox(tmp_path / "sbx")
    link = box.root / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("cannot create symlink")
    with pytest.raises(SandboxEscapeError):
        box.resolve_path("link")
