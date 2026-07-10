"""
utils/prompt_utils.py
"""

from __future__ import annotations

import json
import re
import textwrap
from typing import Any, Dict, List, Optional, Tuple

# 1. Context / character-budget helpers


def truncate_text(text: str, max_chars: int, suffix: str = "...") -> str:
    """
    Hard-truncate *text* to at most *max_chars* characters, appending
    *suffix* if truncation actually occurred.

    Truncates at a word boundary where possible (using `rsplit`) so the
    cut does not land in the middle of a word.  If the text already fits,
    it is returned unchanged.

    Args:
        text:      The source string to (potentially) shorten.
        max_chars: Maximum allowed length of the returned string,
                   *including* the suffix.
        suffix:    Appended only when text is actually truncated.
                   Defaults to "...".

    Returns:
        The (possibly truncated) string, guaranteed to be
        <= max_chars characters.

    Examples:
        >>> truncate_text("Hello world, this is a test.", 20)
        'Hello world, this...'
        >>> truncate_text("Short.", 100)
        'Short.'
    """
    if len(text) <= max_chars:
        return text

    budget = max_chars - len(suffix)
    if budget <= 0:
        return suffix[:max_chars]

    # Prefer cutting at a space so we don't mid-word truncate.
    cut = text[:budget]
    last_space = cut.rfind(" ")
    if last_space > 0:
        cut = cut[:last_space]

    return cut + suffix


def trim_field_value(value: str, max_chars: int = 120) -> str:
    """
    Collapse whitespace and cap a single field value to *max_chars*.

    Used when embedding user-supplied field values directly inside a
    prompt -- keeps individual values from blowing up the token budget.

    Args:
        value:     Raw field value string.
        max_chars: Hard cap per value.  Defaults to 120.

    Returns:
        Normalised and (if necessary) truncated value string.
    """
    normalised = " ".join(value.strip().split())
    return truncate_text(normalised, max_chars)



# 2. Field-dict serialisation

def format_fields_for_prompt(
    fields: Dict[str, Any],
    *,
    max_value_chars: int = 120,
    indent: int = 2,
) -> str:
    """
    Render a field dictionary as indented JSON, trimming long values.

    Agents pass known_fields / assumptions dicts into prompts.  This
    helper ensures no single field value dominates the token budget and
    that the output is always valid, compact JSON -- not Python repr.

    Args:
        fields:          Mapping of field_name -> value.
        max_value_chars: Per-value character cap before truncation.
        indent:          JSON indentation level.

    Returns:
        A JSON-formatted string safe to embed verbatim inside a prompt.
    """
    if not fields:
        return "{}"

    trimmed: Dict[str, Any] = {}
    for key, value in fields.items():
        if isinstance(value, str):
            trimmed[key] = trim_field_value(value, max_value_chars)
        else:
            trimmed[key] = value

    return json.dumps(trimmed, indent=indent, ensure_ascii=False)


def format_list_for_prompt(items: List[str], *, bullet: str = "  - ") -> str:
    """
    Convert a list of strings into a prompt-ready bulleted list.

    Args:
        items:  Strings to render as bullet points.
        bullet: Prefix for each line.  Defaults to two-space "  - ".

    Returns:
        A multi-line string, one bullet per item.  Returns the string
        "  (none)" if *items* is empty.

    Examples:
        >>> format_list_for_prompt(["topic", "audience"])
        '  - topic\n  - audience'
    """
    if not items:
        return "  (none)"
    return "\n".join(f"{bullet}{item}" for item in items)



# 3. Prior-section summary helpers

def build_prior_sections_block(
    prior_sections_summary: Dict[str, str],
    *,
    max_chars_per_section: int = 220,
) -> str:
    """
    Format the rolling prior-sections summary for embedding in a prompt.

    Each entry is trimmed so the cumulative context block stays within a
    predictable token budget, regardless of how many sections have
    already been generated.

    Args:
        prior_sections_summary: Mapping of section_name -> short summary.
        max_chars_per_section:  Per-entry character cap.  Defaults to 220.

    Returns:
        A multi-line string of ``[Section Name]: <trimmed summary>``
        entries, or ``"  (this is the first section)"`` if the dict is
        empty.
    """
    if not prior_sections_summary:
        return "  (this is the first section)"

    lines: List[str] = []
    for name, summary in prior_sections_summary.items():
        trimmed = truncate_text(summary.strip(), max_chars_per_section)
        lines.append(f"  [{name}]: {trimmed}")

    return "\n".join(lines)


# 4. Prompt string post-processing (cleaning LLM output)


def strip_markdown_fences(text: str) -> str:
    """
    Remove triple-backtick code fences that LLMs sometimes add despite
    being explicitly told not to.

    Handles both plain ``` and annotated ```json / ```text variants.
    Does NOT remove inline backticks -- only the opening/closing fence
    lines that wrap the entire response.

    Args:
        text: Raw text response from the LLM.

    Returns:
        The text with leading/trailing fence lines removed.
    """
    stripped = text.strip()
    stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def collapse_blank_lines(text: str, max_consecutive: int = 2) -> str:
    """
    Collapse runs of more than *max_consecutive* blank lines into exactly
    *max_consecutive* blank lines.

    Gemini occasionally inserts large vertical whitespace gaps in
    generated prose.  This helper normalises them without removing
    intentional paragraph breaks.

    Args:
        text:             Input text with potential excess blank lines.
        max_consecutive:  Maximum blank lines to preserve in a row.

    Returns:
        Text with excessive blank-line runs collapsed.
    """
    pattern = r"\n{" + str(max_consecutive + 1) + r",}"
    replacement = "\n" * max_consecutive
    return re.sub(pattern, replacement, text)


def strip_leading_heading(text: str) -> str:
    """
    Remove a leading Markdown heading line (# / ## / ### ...) if the LLM
    repeated the section title at the top of its response.

    Agents instruct Gemini *not* to include the heading, but it
    sometimes does anyway.  This is the deterministic fix that runs
    before saving to DOCX.

    Args:
        text: Section content that may begin with a heading.

    Returns:
        Content with the first heading line removed (if present).
    """
    return re.sub(r"^#{1,6}\s*[^\n]+\n+", "", text.lstrip(), count=1)


def clean_generated_prose(text: str) -> str:
    """
    Apply all standard post-processing steps to a raw LLM prose response.

    Convenience wrapper that chains:
      1. ``strip_markdown_fences``   -- remove code fences
      2. ``strip_leading_heading``   -- remove echoed section title
      3. ``collapse_blank_lines``    -- normalise vertical whitespace
      4. ``str.strip``               -- remove leading/trailing whitespace

    This is the single call ``ContentGeneratorAgent.sanitize_content``
    and ``ReviewerAgent.revise_flagged_sections`` should use rather than
    reimplementing the same chain themselves.

    Args:
        text: Raw text returned by ``GeminiClient.generate_text()``.

    Returns:
        Cleaned prose ready to be stored in a GeneratedSection.
    """
    text = strip_markdown_fences(text)
    text = strip_leading_heading(text)
    text = collapse_blank_lines(text)
    return text.strip()

# 5. Prompt length / token estimation



_CHARS_PER_TOKEN: float = 3.8


def estimate_token_count(text: str) -> int:
    """
    Cheap, offline estimate of the token count for *text*.

    Uses a fixed characters-per-token heuristic (3.8 chars/token) which
    is conservative for English prose and avoids any tokeniser dependency.
    Use this only for budget-checking heuristics, NOT for billing.

    Args:
        text: The string to estimate.

    Returns:
        Approximate token count as an integer (always >= 1 for non-empty
        input, 0 for empty/whitespace-only).
    """
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, int(len(stripped) / _CHARS_PER_TOKEN))


def prompt_fits_in_budget(
    prompt: str,
    *,
    max_tokens: int = 8_000,
) -> Tuple[bool, int]:
    """
    Check whether *prompt* is within the given token budget.

    Args:
        prompt:     The fully-assembled prompt string.
        max_tokens: Token budget to check against.  Defaults to 8 000,
                    a safe limit for the models used in this project.

    Returns:
        A ``(fits, estimated_tokens)`` tuple:
        - ``fits`` is ``True`` when the estimate is <= *max_tokens*.
        - ``estimated_tokens`` is the raw estimate for logging.
    """
    estimated = estimate_token_count(prompt)
    return estimated <= max_tokens, estimated

# 6. Assumption / missing-field formatting helpers


def format_assumptions_summary(
    assumptions: Dict[str, Any],
    *,
    max_value_chars: int = 80,
) -> str:
    """
    Render an assumptions dict as a human-readable summary block.

    Each assumption is rendered as:
        field_name: <value>  (reasoning: <reasoning>)

    Intended for inclusion in log messages or in a follow-up prompt
    that needs to remind the model of previously generated assumptions.

    Args:
        assumptions:     Mapping of field_name -> Assumption-like object
                         or plain dict with ``value`` / ``reasoning`` keys.
        max_value_chars: Per-value cap for the rendered value string.

    Returns:
        Multi-line string, one assumption per line.
        Returns ``"  (no assumptions made)"`` if *assumptions* is empty.
    """
    if not assumptions:
        return "  (no assumptions made)"

    lines: List[str] = []
    for field_name, entry in assumptions.items():
        # Support both dataclass-style (.value / .reasoning) and dict-style.
        if hasattr(entry, "value"):
            value = str(entry.value)
            reasoning = str(getattr(entry, "reasoning", ""))
        elif isinstance(entry, dict):
            value = str(entry.get("value", ""))
            reasoning = str(entry.get("reasoning", ""))
        else:
            value = str(entry)
            reasoning = ""

        value = trim_field_value(value, max_value_chars)
        if reasoning:
            reasoning = trim_field_value(reasoning, max_value_chars)
            lines.append(f"  {field_name}: {value}  (reasoning: {reasoning})")
        else:
            lines.append(f"  {field_name}: {value}")

    return "\n".join(lines)


def build_missing_fields_note(missing_fields: List[str]) -> str:
    """
    Build a concise note string listing which required fields are absent.

    Used to prepend a disclaimer to prompts when the Planner had to fall
    back to assumptions for some fields -- so the content-writing prompt
    can acknowledge the uncertainty without re-listing the full reasoning.

    Args:
        missing_fields: Field names that were not supplied by the user.

    Returns:
        A short human-readable note, or an empty string if the list is
        empty (so callers can safely embed it without conditional checks).

    Examples:
        >>> build_missing_fields_note(["audience", "deadline"])
        'Note: the following fields were not provided and have been assumed: audience, deadline.'
    """
    if not missing_fields:
        return ""
    joined = ", ".join(missing_fields)
    return (
        f"Note: the following fields were not provided and have been assumed: {joined}."
    )


# 7. Dedent / normalise multi-line prompt strings


def dedent_prompt(prompt: str) -> str:
    """
    Strip common leading whitespace from every line of *prompt*.

    Useful when prompt strings are written inside indented Python
    functions and the extra indentation would otherwise be sent to the
    model, wasting tokens and potentially confusing some parsers.

    Args:
        prompt: A (possibly indented) multi-line prompt string.

    Returns:
        The dedented prompt, with leading/trailing blank lines removed.
    """
    return textwrap.dedent(prompt).strip()


def normalise_prompt_whitespace(prompt: str) -> str:
    """
    Collapse internal whitespace runs and trailing spaces per line.

    Does NOT collapse newlines (paragraph/section separators matter in
    prompts).  Only removes trailing spaces on each line and replaces
    runs of more than one space on a single line with a single space.

    Args:
        prompt: Raw prompt string.

    Returns:
        Prompt with per-line whitespace normalised.
    """
    lines = prompt.split("\n")
    cleaned = [re.sub(r"[ \t]+", " ", line).rstrip() for line in lines]
    return "\n".join(cleaned)
