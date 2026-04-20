"""Pytest shared fixtures."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest


@pytest.fixture
def tmp_output_dir() -> Iterator[str]:
    """A temporary OUTPUT_DIRECTORY for tests that touch the filesystem."""
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Strip known settings env vars so tests see a predictable baseline."""
    for var in (
        "OUTPUT_DIRECTORY",
        "CLEANUP_RETENTION_DAYS",
        "VIDEO_FILENAME_FORMAT",
        "TRANSPORT",
        "HOST",
        "PORT",
        "MCP_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch
