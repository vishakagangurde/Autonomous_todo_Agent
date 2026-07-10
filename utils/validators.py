"""
utils/validators.py

Deterministic validation logic used throughout the pipeline.

This file is also where LLM output is treated as untrusted input:
Gemini's raw text/JSON responses are parsed and normalized here
before they are ever used to construct a Pydantic model elsewhere in
the pipeline.
"""

import json
import logging
import re
from typing import Any, Optional

from utils.constants import DocumentType
from models.planner_models import MissingField

logger = logging.getLogger(__name__)


class GeminiResponseParsingError(Exception):
    """
    Raised when Gemini's raw response cannot be parsed into usable
    JSON, even after cleanup attempts.

    A distinct exception type (rather than letting json.JSONDecodeError
    propagate raw) lets callers catch LLM-parsing failures specifically,
    separate from other error classes in the pipeline.
    """


def extract_json_from_llm_response(raw_text: str) -> dict[str, Any]:
    """
    Safely parse a JSON object out of Gemini's raw text response.

    LLMs frequently wrap JSON in markdown code fences (```json ... ```)
    or add explanatory text before/after the JSON block, even when
    explicitly instructed not to. This function strips common wrapping
    patterns before attempting to parse, and raises a clear,
    actionable error if parsing still fails — rather than letting a
    cryptic json.JSONDecodeError propagate into an agent.

    Args:
        raw_text: The raw string returned by the Gemini client.

    Returns:
        Parsed JSON as a Python dict.

    Raises:
        GeminiResponseParsingError: if no valid JSON object can be
            extracted from the text.
    """
    if not raw_text or not raw_text.strip():
        raise GeminiResponseParsingError(
            "Gemini returned an empty response where JSON was expected."
        )

    cleaned = raw_text.strip()

    # Strip markdown code fences, e.g. ```json ... ``` or ``` ... ```
    fence_pattern = r"^```(?:json)?\s*(.*?)\s*```$"
    fence_match = re.match(fence_pattern, cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Last resort: extract the first {...} block found anywhere
        # in the text, in case the model added preamble/postamble.
        brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not brace_match:
            raise GeminiResponseParsingError(
                f"Could not extract valid JSON from Gemini response. "
                f"Raw response (truncated): {raw_text[:300]!r}"
            )
        try:
            parsed = json.loads(brace_match.group(0))
        except json.JSONDecodeError as exc:
            raise GeminiResponseParsingError(
                f"Failed to parse extracted JSON block from Gemini "
                f"response: {exc}. Raw response (truncated): "
                f"{raw_text[:300]!r}"
            ) from exc

    if not isinstance(parsed, dict):
        raise GeminiResponseParsingError(
            f"Expected a JSON object from Gemini, got {type(parsed).__name__}."
        )

    return parsed


def normalize_document_type(raw_value: str) -> Optional[DocumentType]:
    """
    Normalize Gemini's classification output into a strict DocumentType.

    Gemini may return the correct value with different casing, extra
    whitespace, or spaces instead of underscores (e.g. "Business
    Proposal" instead of "business_proposal") even when explicitly
    prompted for the exact enum value. This function absorbs that
    variance in one place instead of scattering defensive string
    handling across every agent.

    Args:
        raw_value: The raw string returned by Gemini's Intent Classifier.

    Returns:
        A valid DocumentType if a match is found, otherwise None
        (callers should fall back to DocumentType.GENERIC_REPORT rather
        than raise, since a wrong classification shouldn't crash the
        whole request).
    """
    if not raw_value:
        return None

    normalized = raw_value.strip().lower().replace(" ", "_").replace("-", "_")

    for doc_type in DocumentType:
        if doc_type.value == normalized:
            return doc_type

    logger.warning(
        "Could not normalize document type '%s' (normalized to '%s') "
        "into a known DocumentType. Falling back to GENERIC_REPORT.",
        raw_value,
        normalized,
    )
    return None


def detect_missing_fields(
    required_fields: tuple[str, ...],
    extracted_fields: dict[str, str],
) -> list[MissingField]:
    """
    Compute which required fields were not present in the extracted
    information — pure Python set difference, no Gemini call.

    Args:
        required_fields: Field names required by the document template.
        extracted_fields: Field names Gemini's Information Extractor
            successfully pulled from the user's request.

    Returns:
        A MissingField entry for every required field absent from
        extracted_fields (or present but blank).
    """
    missing: list[MissingField] = []
    for field_name in required_fields:
        value = extracted_fields.get(field_name)
        if value is None or not str(value).strip():
            missing.append(
                MissingField(
                    field_name=field_name,
                    reason=f"'{field_name}' was not provided in the original request.",
                )
            )
    return missing


def compare_expected_vs_generated_sections(
    expected_sections: list[str],
    generated_section_names: list[str],
) -> list[str]:
    """
    Identify which expected template sections were never generated.

    Used by the Review Agent's "detect missing sections" responsibility.
    Order-preserving and case-insensitive to tolerate minor formatting
    drift from the Content Generation Agent.

    Args:
        expected_sections: Section names defined by the document template.
        generated_section_names: Section names actually produced so far.

    Returns:
        List of expected section names with no corresponding generated
        section, in the original template order.
    """
    generated_normalized = {name.strip().lower() for name in generated_section_names}
    return [
        section
        for section in expected_sections
        if section.strip().lower() not in generated_normalized
    ]


def is_section_content_too_short(content: str, min_word_count: int = 15) -> bool:
    """
    Cheap, deterministic quality heuristic: flag suspiciously short
    section content BEFORE spending a Gemini call on quality review.

    This is intentionally conservative — it only catches the obvious
    failure case (near-empty generation, e.g. Gemini returned "N/A" or
    a one-word stub). Genuine quality judgment (is this well-written?
    does it address the topic?) is still Gemini's job in the Review
    Agent; this function exists purely to short-circuit the cheap,
    obvious cases without spending a token on them.
    """
    word_count = len(content.strip().split())
    return word_count < min_word_count