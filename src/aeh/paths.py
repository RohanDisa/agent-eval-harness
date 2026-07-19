"""Repo-root resolution. Engine code must not import suite packages."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
