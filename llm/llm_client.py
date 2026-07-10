"""
llm/llm_client.py

The single, exclusive boundary between this codebase and the NVIDIA NIM API.

Rule enforced by this file's existence: no other file in the project
is permitted to import `openai` directly for LLM calls. All NIM access
goes through NvidiaClient.generate_json() / generate_text().

Everything in this file except the actual API call is pure, deterministic
Python: retries, fence-stripping, JSON validation, and logging.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, Optional

from openai import OpenAI

from config import get_settings
from utils.constants import (
    GEMINI_MAX_RETRIES,
    GEMINI_RETRY_BACKOFF_SECONDS,
    GEMINI_REQUEST_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

# NVIDIA NIM OpenAI-compatible base URL
_NVIDIA_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"


class LLMClientError(Exception):
    """
    Raised when the LLM fails to produce usable JSON after all retries.

    Deliberately a distinct exception type (not a bare Exception) so that
    callers (agents) can catch this specifically and decide on fallback
    behavior, per Pydantic/SOLID error-handling best practice: never let
    callers guess what went wrong from a generic exception.
    """

    def __init__(self, message: str, raw_response: Optional[str] = None) -> None:
        super().__init__(message)
        self.raw_response = raw_response


class NvidiaClient:
    """
    Thin, defensive wrapper around NVIDIA NIM (OpenAI-compatible API).

    Single Responsibility: send a prompt string, return a parsed dict.
    Nothing in this class knows what the prompt *means* — that knowledge
    lives entirely in llm/prompts.py and the calling agent.

    Uses the OpenAI SDK pointed at NVIDIA's NIM endpoint so migration
    to/from other OpenAI-compatible providers is a one-line base_url change.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = OpenAI(
            base_url=_NVIDIA_NIM_BASE_URL,
            api_key=settings.nvidia_api_key,
        )
        self._model_name = settings.nvidia_model_name
        logger.info("NvidiaClient initialized with model=%s", self._model_name)

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------
    def generate_json(self, prompt: str) -> Dict[str, Any]:
        """
        Sends `prompt` to NVIDIA NIM and returns a parsed JSON dict.

        This is the ONLY public method agents should call for structured
        data. It internally handles retries and fence-stripping so agents
        never deal with raw model text.

        Raises:
            LLMClientError: if all retries are exhausted without
                producing valid, parseable JSON.
        """
        last_error: Optional[Exception] = None
        raw_text: Optional[str] = None

        for attempt in range(1, GEMINI_MAX_RETRIES + 1):
            try:
                raw_text = self._call_llm(prompt)
                cleaned = self._strip_markdown_fences(raw_text)
                parsed = self._parse_json(cleaned)
                logger.info("NIM call succeeded on attempt %d/%d", attempt, GEMINI_MAX_RETRIES)
                return parsed

            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "NIM JSON parse failed on attempt %d/%d: %s",
                    attempt,
                    GEMINI_MAX_RETRIES,
                    exc,
                )
            except Exception as exc:  # network / SDK-level errors
                last_error = exc
                logger.warning(
                    "NIM call failed on attempt %d/%d: %s",
                    attempt,
                    GEMINI_MAX_RETRIES,
                    exc,
                )

            if attempt < GEMINI_MAX_RETRIES:
                sleep_seconds = GEMINI_RETRY_BACKOFF_SECONDS * attempt
                logger.info("Retrying in %.1fs...", sleep_seconds)
                time.sleep(sleep_seconds)

        raise LLMClientError(
            f"NIM failed to return valid JSON after {GEMINI_MAX_RETRIES} attempts: {last_error}",
            raw_response=raw_text,
        )

    def generate_text(self, prompt: str) -> str:
        """
        Sends `prompt` to NVIDIA NIM and returns the raw text response.

        Used by agents that need prose output (e.g. ContentGeneratorAgent
        and ReviewerAgent when rewriting sections) rather than structured
        JSON. Retries on network/SDK errors but does NOT retry on content
        issues — raw text is always accepted as-is.

        Raises:
            LLMClientError: if all retries are exhausted without a
                non-empty response from NIM.
        """
        last_error: Optional[Exception] = None

        for attempt in range(1, GEMINI_MAX_RETRIES + 1):
            try:
                raw_text = self._call_llm(prompt)
                logger.info(
                    "NIM text call succeeded on attempt %d/%d",
                    attempt,
                    GEMINI_MAX_RETRIES,
                )
                return raw_text

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "NIM text call failed on attempt %d/%d: %s",
                    attempt,
                    GEMINI_MAX_RETRIES,
                    exc,
                )

            if attempt < GEMINI_MAX_RETRIES:
                sleep_seconds = GEMINI_RETRY_BACKOFF_SECONDS * attempt
                logger.info("Retrying in %.1fs...", sleep_seconds)
                time.sleep(sleep_seconds)

        raise LLMClientError(
            f"NIM failed to return a text response after {GEMINI_MAX_RETRIES} attempts: {last_error}",
        )

    # ------------------------------------------------------------------
    # PRIVATE: NETWORK CALL (the ONLY non-deterministic part of this file)
    # ------------------------------------------------------------------
    def _call_llm(self, prompt: str) -> str:
        """
        Performs the actual NVIDIA NIM API call via OpenAI-compatible SDK.

        This is intentionally the smallest possible method — it does
        exactly one thing (call the model, return raw text) so that if
        something breaks here, you know immediately it's an SDK/network
        issue and not a parsing issue.
        """
        response = self._client.chat.completions.create(
            model=self._model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2048,
            timeout=120,  # generous timeout for free-tier NIM
        )

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise ValueError("NVIDIA NIM returned an empty response")

        return content

    # ------------------------------------------------------------------
    # PRIVATE: DETERMINISTIC PYTHON HELPERS (no reasoning, pure string ops)
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        """
        Defensively removes ```json / ``` fences some models add despite
        being told not to.
        """
        stripped = text.strip()
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
        return stripped.strip()

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        """
        Parses cleaned text into a dict.

        Deliberately a plain `json.loads` — no regex-based JSON extraction,
        no "best effort" scraping. If the model didn't produce valid JSON
        after the fence-stripping above, we want a loud, explicit failure
        (caught by the retry loop) rather than a silently wrong dict.
        """
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected a JSON object, got {type(parsed).__name__}")
        return parsed


# MODULE-LEVEL SINGLETON

_client_instance: Optional[NvidiaClient] = None


def get_llm_client() -> NvidiaClient:
    """
    Returns a process-wide singleton NvidiaClient.


    """
    global _client_instance
    if _client_instance is None:
        _client_instance = NvidiaClient()
    return _client_instance


# directly (outside the singleton) will still work.
GeminiClient = NvidiaClient