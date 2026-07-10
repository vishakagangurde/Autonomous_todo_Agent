"""
config.py

Centralized application configuration.

Single source of truth for:
    - NVIDIA NIM API credentials and model selection
    - Output/file-system paths
    - Logging configuration
    - Request/timeout tuning

Every other module MUST import `settings` from this file instead of
reading environment variables directly. This keeps configuration
concerns out of business logic and makes the system's environment-
dependent behavior auditable from one place.
"""

import logging
import sys
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """
    Application-wide configuration, loaded from environment variables
    and/or a local `.env` file.

    Attributes:
        nvidia_api_key: API key used to authenticate with NVIDIA NIM.
        nvidia_model_name: Which model powers all reasoning agents via NVIDIA NIM.
        nvidia_request_timeout_seconds: Hard timeout for any single NIM call.
        nvidia_max_retries: Number of retry attempts on transient NIM failures.

        app_name: Human-readable app name, used in logs and API docs.
        log_level: Logging verbosity (DEBUG, INFO, WARNING, ERROR).

        output_dir: Root directory where generated DOCX files are saved.
        max_request_length: Upper bound on incoming `request` string length,
            used by utils/validators.py to reject abusive input early.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- NVIDIA NIM configuration --------------------------------------------
    nvidia_api_key: str = Field(
        ...,
        description="NVIDIA NIM API key. Must be set via environment variable "
                     "NVIDIA_API_KEY or a .env file. No default is provided "
                     "on purpose — the app must fail fast if this is missing.",
    )
    nvidia_model_name: str = Field(
        default="meta/llama-3.1-8b-instruct",
        description="NVIDIA NIM model used for ALL reasoning agents "
                     "(Planner, Content, Review). Changing models is a "
                     "one-line change here, never scattered across agents.",
    )
    nvidia_request_timeout_seconds: int = Field(default=60, ge=1)
    nvidia_max_retries: int = Field(default=2, ge=0, le=5)

    # ---- Application metadata --------------------------------------------------
    app_name: str = Field(default="Autonomous DOCX Agent")
    log_level: str = Field(default="INFO")

    # ---- File system -------------------------------------------------------
    output_dir: Path = Field(default=Path("outputs"))
    max_request_length: int = Field(default=4000, ge=1)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Ensure log_level is one of the standard logging levels."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        normalized = value.upper()
        if normalized not in allowed:
            raise ValueError(
                f"Invalid log_level '{value}'. Must be one of {sorted(allowed)}."
            )
        return normalized

    @field_validator("nvidia_api_key")
    @classmethod
    def validate_api_key_not_empty(cls, value: str) -> str:
        """Fail fast if the API key is present but blank."""
        if not value or not value.strip():
            raise ValueError(
                "NVIDIA_API_KEY is set but empty. Provide a real NVIDIA NIM API key."
            )
        return value.strip()

    def ensure_output_dir_exists(self) -> None:
        """
        Create the output directory if it does not already exist.

        Deterministic file-system operation — pure Python, no Gemini
        involvement. Called once at application startup.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)


def _configure_logging(level: str) -> None:
    """
    Configure root logging once, at import time.

    Centralizing this here (rather than calling logging.basicConfig in
    multiple files) prevents duplicate handlers and inconsistent formats
    across agents, services, and the FastAPI layer.
    """
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached, process-wide Settings instance.

    Using lru_cache guarantees Settings is constructed exactly once
    (avoids re-parsing environment variables / .env on every import)
    while still allowing tests to bypass the cache via
    `get_settings.cache_clear()` when injecting a different environment.
    """
    loaded_settings = Settings()
    _configure_logging(loaded_settings.log_level)
    loaded_settings.ensure_output_dir_exists()
    return loaded_settings


# Module-level singleton — this is what every other file should import:
#     from config import settings
settings = get_settings()