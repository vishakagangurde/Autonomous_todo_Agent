"""
utils/constants.py

Central registry of fixed values used across the entire system:
document types, task/section statuses, and shared string/file constants.

Design rule: if a value appears as a raw string literal in more than one
file, it belongs here instead. This file has zero dependencies and
zero logic beyond definition — it exists purely to eliminate magic
strings and typo-class bugs across agents.
"""

from enum import Enum


class DocumentType(str, Enum):
    """
    The closed set of document types this system knows how to produce.
    """

    BUSINESS_PROPOSAL = "business_proposal"
    PROJECT_PLAN = "project_plan"
    MEETING_MINUTES = "meeting_minutes"
    BUSINESS_REPORT = "business_report"
    TECHNICAL_DESIGN = "technical_design"
    SOP = "sop"
    PRODUCT_SPECIFICATION = "product_specification"
    GENERIC_REPORT = "generic_report"


class TaskStatus(str, Enum):
    """
    Lifecycle states for a single task inside an ExecutionPlan.

    Used by the Content Generation Agent as it works through the
    Planner's task list, and by the Orchestrator to determine whether
    execution completed cleanly.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SectionStatus(str, Enum):
    """
    Quality/completeness state of a single generated document section,
    as judged by the Review Agent.

    APPROVED sections are left untouched. NEEDS_REGENERATION sections
    are sent back to the Content Generation Agent. MISSING sections
    were expected (per the template) but never produced.
    """

    APPROVED = "approved"
    NEEDS_REGENERATION = "needs_regeneration"
    MISSING = "missing"


class RequestStatus(str, Enum):
    """
    Overall status of a single /agent request, returned in the API response.
    """

    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"

# File / output constants


DOCX_FILE_EXTENSION: str = ".docx"
DEFAULT_FILENAME_PREFIX: str = "generated_document"
MAX_FILENAME_LENGTH: int = 80


# LLM (NVIDIA NIM) related constants (NOT credentials — those stay in config.py)
GEMINI_JSON_RESPONSE_MIME_TYPE: str = "application/json"

# Maximum number of attempts (initial call + retries) for a single LLM call.
GEMINI_MAX_RETRIES: int = 3

# Seconds to multiply by attempt number for exponential-ish back-off between
# retries (e.g. attempt 1 => 2s, attempt 2 => 4s).
GEMINI_RETRY_BACKOFF_SECONDS: float = 2.0

# Hard timeout (seconds) for a single LLM API call.
GEMINI_REQUEST_TIMEOUT_SECONDS: int = 60

# rather than looping indefinitely on a stubborn low-quality section.
MAX_REGENERATION_ATTEMPTS_PER_SECTION: int = 2

# ---------------------------------------------------------------------------
# Logging tags — used as structured prefixes so log lines are greppable
# per-agent during debugging (e.g. grep "[PLANNER]" server.log)
# ---------------------------------------------------------------------------

LOG_TAG_PLANNER: str = "[PLANNER]"
LOG_TAG_CONTENT_GENERATOR: str = "[CONTENT_GENERATOR]"
LOG_TAG_REVIEWER: str = "[REVIEWER]"
LOG_TAG_DOCUMENT_GENERATOR: str = "[DOCUMENT_GENERATOR]"
LOG_TAG_ORCHESTRATOR: str = "[ORCHESTRATOR]"