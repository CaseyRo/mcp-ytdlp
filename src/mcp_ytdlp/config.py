"""Configuration loaded from environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # yt-dlp output
    output_directory: str = "/data"
    cleanup_retention_days: int = 7
    video_filename_format: str | None = None

    # Server transport
    transport: Literal["stdio", "http"] = "http"
    host: str = "127.0.0.1"
    port: int = 8000

    # Bearer token auth for MCP Portal
    mcp_api_key: SecretStr = SecretStr("")

    model_config = {"env_prefix": "", "case_sensitive": False}

    @field_validator("cleanup_retention_days")
    @classmethod
    def validate_retention(cls, v: int) -> int:
        if v < 1:
            raise ValueError("CLEANUP_RETENTION_DAYS must be >= 1")
        return v

    @model_validator(mode="after")
    def require_api_key_for_http(self) -> "Settings":
        if self.transport == "http" and not self.mcp_api_key.get_secret_value():
            raise ValueError(
                "MCP_API_KEY is required when TRANSPORT=http. "
                "Refusing to start an unauthenticated server."
            )
        return self


settings = Settings()
