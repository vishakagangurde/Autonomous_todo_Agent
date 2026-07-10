"""
services/document_service.py

Service layer for document generation operations.

Sits between the FastAPI route handlers (app.py) and the Orchestrator,
providing a clean, testable interface for the document generation
pipeline. This layer also handles request-level logging and timing
so that the HTTP layer stays thin.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from agents.orchestrator import OrchestratorAgent, OrchestratorError
from models.response import AgentResponse

logger = logging.getLogger(__name__)


class DocumentService:
    """
    Service facade for document generation.

    Provides the single public method `generate()` that the FastAPI
    route handler calls. All agent orchestration is delegated to
    OrchestratorAgent; this class only adds service-level concerns:
    request logging, elapsed time tracking, and error translation.
    """

    def __init__(self) -> None:
        """
        Instantiate the orchestrator once per service instance.

        The orchestrator itself instantiates a shared GeminiClient and
        all four agents — this init is intentionally lightweight at the
        service level (no Gemini calls, no file I/O).
        """
        self._orchestrator = OrchestratorAgent()

    def generate(self, user_request: str) -> AgentResponse:
        """
        Generate a document from a natural-language request.

        This is the primary entry point for the FastAPI route handler.

        Args:
            user_request: The raw request string from the API caller,
                already validated by models/request.py before reaching
                this method.

        Returns:
            AgentResponse with status, file_path, and plan_summary
            populated by the pipeline. Always returns (never raises) —
            failures are captured as AgentResponse.failure() objects.
        """
        start = time.monotonic()
        logger.info(
            "DocumentService.generate() called (request_len=%d)",
            len(user_request),
        )

        try:
            response = self._orchestrator.run(user_request)
        except Exception as exc:  # noqa: BLE001
            # Catch anything OrchestratorAgent itself didn't handle
            # (should not happen, but belt-and-suspenders).
            logger.exception("Unhandled exception in OrchestratorAgent.run()")
            response = AgentResponse.failure(
                error_detail=f"Internal pipeline error: {exc}",
                message="An unexpected error occurred during document generation.",
            )

        elapsed = time.monotonic() - start
        logger.info(
            "DocumentService.generate() complete: status=%s, elapsed=%.2fs",
            response.status,
            elapsed,
        )
        return response

    def get_pipeline_metadata(self) -> Dict[str, Any]:
        """
        Return metadata about the pipeline configuration.

        """
        from config import settings

        return {
            "model": settings.nvidia_model_name,
            "output_dir": str(settings.output_dir),
            "max_request_length": settings.max_request_length,
            "max_retries": settings.nvidia_max_retries,
        }
