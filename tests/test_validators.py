"""URL and cookies_file validators — defence against SSRF and path traversal."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch: pytest.MonkeyPatch, tmp_output_dir: str):
    """Point OUTPUT_DIRECTORY at a tmp dir before server.py imports run."""
    monkeypatch.setenv("OUTPUT_DIRECTORY", tmp_output_dir)
    monkeypatch.setenv("MCP_API_KEY", "test-key")
    monkeypatch.setenv("TRANSPORT", "stdio")
    # Force a fresh import so OUTPUT_DIR picks up the tmp path.
    import sys

    for mod in list(sys.modules):
        if mod.startswith("mcp_ytdlp"):
            del sys.modules[mod]


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///etc/passwd",
        "data:text/plain,hello",
        "ftp://example.com/file.txt",
        "javascript:alert(1)",
    ],
)
def test_rejects_non_http_schemes(bad_url):
    from mcp_ytdlp.server import _validate_url

    with pytest.raises(ValueError, match="Disallowed URL scheme"):
        _validate_url(bad_url)


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://localhost/x",
        "http://127.0.0.1/x",
        "http://0.0.0.0/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/x",
    ],
)
def test_rejects_loopback_and_link_local(bad_url):
    from mcp_ytdlp.server import _validate_url

    with pytest.raises(ValueError, match="Disallowed URL host"):
        _validate_url(bad_url)


def test_accepts_normal_https_url():
    from mcp_ytdlp.server import _validate_url

    _validate_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")


def test_cookies_path_rejects_traversal(tmp_output_dir):
    from mcp_ytdlp.server import _validate_cookies_path

    with pytest.raises(ValueError, match="plain filename"):
        _validate_cookies_path("../etc/passwd")
    with pytest.raises(ValueError, match="plain filename"):
        _validate_cookies_path("sub/cookies.txt")


def test_cookies_path_requires_existing_file(tmp_output_dir):
    from mcp_ytdlp.server import _validate_cookies_path

    with pytest.raises(ValueError, match="not found"):
        _validate_cookies_path("nonexistent.txt")


def test_cookies_path_accepts_real_file(tmp_output_dir):
    from mcp_ytdlp.server import _validate_cookies_path

    cookies = Path(tmp_output_dir) / "cookies.txt"
    cookies.write_text("# netscape cookies\n")

    resolved = _validate_cookies_path("cookies.txt")
    assert resolved == cookies.resolve()
