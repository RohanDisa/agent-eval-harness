"""Per-attempt temp directory. Never reused. Deleted after the final-state hash."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

from aeh.errors import SandboxEscapeError


class Sandbox:
    def __init__(self, root: Path | None = None) -> None:
        self._owns_root = root is None
        self.root = (root or Path(tempfile.mkdtemp(prefix="aeh-"))).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, user_path: str) -> Path:
        """Resolve a user-supplied path and reject anything outside root."""
        raw = Path(user_path)
        if raw.is_absolute():
            candidate = raw
        else:
            candidate = self.root / raw
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise SandboxEscapeError(f"cannot resolve path '{user_path}': {exc}") from exc
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise SandboxEscapeError(
                f"path '{user_path}' escapes sandbox root {self.root}"
            ) from exc
        # Symlink that escaped would already fail relative_to after resolve().
        if resolved.is_symlink():
            target = resolved.resolve()
            try:
                target.relative_to(self.root)
            except ValueError as exc:
                raise SandboxEscapeError(f"symlink '{user_path}' points outside sandbox") from exc
        return resolved

    def seed_file(self, dest: str, source: Path) -> Path:
        target = self.resolve_path(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target  # noqa: RET504

    def write_text(self, dest: str, content: str) -> Path:
        target = self.resolve_path(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def read_text(self, dest: str) -> str:
        target = self.resolve_path(dest)
        return target.read_text(encoding="utf-8")

    def list_files(self, dest: str = ".") -> list[str]:
        target = self.resolve_path(dest)
        if not target.exists():
            raise FileNotFoundError(str(target))
        if target.is_file():
            return [str(target.relative_to(self.root)).replace("\\", "/")]
        entries: list[str] = []
        for path in sorted(target.rglob("*")):
            if path.is_file():
                entries.append(str(path.relative_to(self.root)).replace("\\", "/"))
        return entries

    def snapshot(self) -> dict[str, Any]:
        files: dict[str, dict[str, Any]] = {}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(self.root)).replace("\\", "/")
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            entry: dict[str, Any] = {"sha256": digest, "size": len(raw)}
            if len(raw) <= 1_000_000:
                try:
                    entry["text"] = raw.decode("utf-8")
                except UnicodeDecodeError:
                    entry["text"] = None
            files[rel] = entry
        return {"root": str(self.root), "files": files}

    def cleanup(self) -> None:
        if self._owns_root and self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)


def apply_resource_limits() -> None:
    """Best-effort POSIX rlimits. No-op on Windows."""
    try:
        import resource
    except ImportError:
        return
    # 256 MiB address space, 64 open files — keep a laptop from melting.
    for name, value in (
        ("RLIMIT_AS", 256 * 1024 * 1024),
        ("RLIMIT_NOFILE", 64),
    ):
        limit = getattr(resource, name, None)
        if limit is None:
            continue
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            continue


def seed_setup(sandbox: Sandbox, files: dict[str, str], repo_root: Path) -> None:
    for dest, fixture in files.items():
        source = Path(fixture)
        if not source.is_absolute():
            source = (repo_root / fixture).resolve()
        sandbox.seed_file(dest, source)
