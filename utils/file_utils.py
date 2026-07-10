"""
utils/file_utils.py

Deterministic file-system utilities used by the Document Generator
Agent: safe filename generation, output path resolution, and
directory management.

"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from utils.constants import (
    DOCX_FILE_EXTENSION,
    DEFAULT_FILENAME_PREFIX,
    MAX_FILENAME_LENGTH,
)

logger = logging.getLogger(__name__)

# Matches any character that is NOT alphanumeric, underscore, or hyphen.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^a-zA-Z0-9_\-]")


def sanitize_filename_component(raw: str) -> str:
    """
    Strip a raw string down to filesystem-safe characters only.

    Replaces spaces with underscores and removes anything that isn't
    alphanumeric, an underscore, or a hyphen. This is what prevents a
    document type or topic string from producing an invalid or
    dangerous filename (path traversal characters, slashes, quotes).

    Args:
        raw: The raw string to sanitize (e.g. a document type value).

    Returns:
        A sanitized string safe to use as part of a filename.
    """
    replaced_spaces = raw.strip().replace(" ", "_")
    sanitized = _UNSAFE_FILENAME_CHARS.sub("", replaced_spaces)
    return sanitized or DEFAULT_FILENAME_PREFIX


def generate_safe_filename(document_type_value: str) -> str:
    """
    Build a collision-resistant, filesystem-safe filename for a
    generated document.

    Format: {document_type}_{YYYYMMDD_HHMMSS}.docx

    Using a UTC timestamp (rather than a random UUID) keeps filenames
    human-readable and naturally sortable in a file listing, while
    still being collision-resistant for any realistic request rate in
    this assignment's context (single-instance demo/interview usage,
    not high-concurrency production traffic).

    Args:
        document_type_value: The DocumentType enum's string value,
            e.g. "business_proposal".

    Returns:
        A safe filename, truncated to MAX_FILENAME_LENGTH if needed.
    """
    safe_type = sanitize_filename_component(document_type_value)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_type}_{timestamp}{DOCX_FILE_EXTENSION}"

    if len(filename) > MAX_FILENAME_LENGTH:
        # Truncate the type component only, never the timestamp or
        # extension — the timestamp is what guarantees uniqueness.
        overflow = len(filename) - MAX_FILENAME_LENGTH
        safe_type = safe_type[: max(1, len(safe_type) - overflow)]
        filename = f"{safe_type}_{timestamp}{DOCX_FILE_EXTENSION}"

    return filename


def resolve_output_path(filename: str) -> Path:
    """
    Resolve a filename into a full path inside the configured output
    directory, ensuring the directory exists first.

    Args:
        filename: A filename produced by generate_safe_filename().

    Returns:
        Absolute Path where the .docx should be saved.
    """
    ensure_directory_exists(settings.output_dir)
    return (settings.output_dir / filename).resolve()


def ensure_directory_exists(directory: Path) -> None:
    """
    Create a directory (and any missing parents) if it doesn't exist.

    Idempotent — safe to call on every request without checking first.
    """
    directory.mkdir(parents=True, exist_ok=True)


def get_relative_output_path(full_path: Path) -> str:
    """
    Convert an absolute output path back into a path relative to the
    project's output directory, for inclusion in the API response.

    Returning a relative path (rather than an absolute server
    filesystem path) in the API response avoids leaking server
    directory structure to the client.

    Args:
        full_path: Absolute path returned by resolve_output_path().

    Returns:
        String path relative to settings.output_dir, e.g.
        "outputs/business_proposal_20260706_143012.docx".
    """
    try:
        relative = full_path.relative_to(settings.output_dir.resolve())
        return str(settings.output_dir / relative)
    except ValueError:
        # full_path wasn't actually inside output_dir — fall back to
        # just the filename rather than leaking an unexpected path.
        logger.warning(
            "Path %s was not inside configured output_dir %s; "
            "returning filename only.",
            full_path,
            settings.output_dir,
        )
        return str(settings.output_dir / full_path.name)