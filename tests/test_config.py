"""Settings behaviour — defaults, validation, and fail-fast for HTTP mode."""

from __future__ import annotations

import pytest


def test_defaults_with_api_key(clean_env, tmp_output_dir):
    clean_env.setenv("OUTPUT_DIRECTORY", tmp_output_dir)
    clean_env.setenv("MCP_API_KEY", "test-key")

    from mcp_ytdlp.config import Settings

    s = Settings()
    assert s.output_directory == tmp_output_dir
    assert s.cleanup_retention_days == 7
    assert s.transport == "http"
    assert s.host == "127.0.0.1"
    assert s.port == 8000
    assert s.mcp_api_key.get_secret_value() == "test-key"


def test_http_mode_requires_api_key(clean_env, tmp_output_dir):
    clean_env.setenv("OUTPUT_DIRECTORY", tmp_output_dir)
    clean_env.setenv("TRANSPORT", "http")

    from mcp_ytdlp.config import Settings

    with pytest.raises(ValueError, match="MCP_API_KEY is required"):
        Settings()


def test_stdio_mode_allows_empty_api_key(clean_env, tmp_output_dir):
    clean_env.setenv("OUTPUT_DIRECTORY", tmp_output_dir)
    clean_env.setenv("TRANSPORT", "stdio")

    from mcp_ytdlp.config import Settings

    s = Settings()
    assert s.mcp_api_key.get_secret_value() == ""


def test_retention_days_must_be_positive(clean_env, tmp_output_dir):
    clean_env.setenv("OUTPUT_DIRECTORY", tmp_output_dir)
    clean_env.setenv("MCP_API_KEY", "test-key")
    clean_env.setenv("CLEANUP_RETENTION_DAYS", "0")

    from mcp_ytdlp.config import Settings

    with pytest.raises(ValueError, match="CLEANUP_RETENTION_DAYS"):
        Settings()


def test_secret_not_in_repr(clean_env, tmp_output_dir):
    clean_env.setenv("OUTPUT_DIRECTORY", tmp_output_dir)
    clean_env.setenv("MCP_API_KEY", "super-secret")

    from mcp_ytdlp.config import Settings

    s = Settings()
    assert "super-secret" not in repr(s)
    assert "super-secret" not in str(s)
