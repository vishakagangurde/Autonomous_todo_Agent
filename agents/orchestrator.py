"""
agents/orchestrator.py

The Orchestrator: the top-level coordinator that wires together all four
agents (Planner -> ContentGenerator -> Reviewer -> DocumentGenerator)
into a single, end-to-end pipeline run.

tree:

    OrchestratorAgent.run()
    │
    ├── PlannerAgent.create_plan()           
    ├── ContentGeneratorAgent.generate_document()  
    ├── ReviewerAgent.review_document()            
    └── DocumentGeneratorAgent.generate_docx()    
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from agents.content_generator import ContentGeneratorAgent, ContentGeneratorAgentError
from agents.document_generator import DocumentGeneratorAgent, DocumentGeneratorAgentError
from agents.planner import PlannerAgent, PlannerAgentError
from agents.reviewer import ReviewerAgent, ReviewerAgentError
from llm.llm_client import GeminiClient
from models.response import AgentResponse
from utils.constants import RequestStatus

logger = logging.getLogger(__name__)


class OrchestratorError(Exception):
    """
    Raised when the Orchestrator detects an unrecoverable pipeline failure
    that none of the individual agents were able to handle internally.
    """


class OrchestratorAgent:
    """
    Single Responsibility: wire the four-agent pipeline together and
    return an AgentResponse to the caller.
    """

    def __init__(self, llm_client: Optional[GeminiClient] = None) -> None:
        """
        Set up the shared GeminiClient and instantiate all four agents.
        """
        from llm.llm_client import get_llm_client

        self._llm = llm_client or get_llm_client()
        self._planner = PlannerAgent(self._llm)
        self._content_generator = ContentGeneratorAgent(self._llm)
        self._reviewer = ReviewerAgent(self._llm)
        self._doc_generator = DocumentGeneratorAgent()

    # ------------------------------------------------------------------
    # PUBLIC ENTRYPOINT
    # ------------------------------------------------------------------
    def run(self, user_request: str) -> AgentResponse:
        """

        Execute the full four-agent pipeline for a single user request.

        Pipeline stages (in order):
            1. PLAN    — PlannerAgent converts the request to an ExecutionPlan.
            2. CONTENT — ContentGeneratorAgent fills each section.
            3. REVIEW  — ReviewerAgent checks and revises flagged sections.
            4. DOCX    — DocumentGeneratorAgent writes the final .docx.
        """
        start_time = time.monotonic()
        logger.info("Pipeline started for request (len=%d)", len(user_request))

        # ---- Stage 1: Plan -----------------------------------------------
        t0 = time.monotonic()
        try:
            plan = self._planner.create_plan(user_request)
        except PlannerAgentError as exc:
            logger.error("Pipeline failed at PLAN stage: %s", exc)
            return AgentResponse.failure(
                error_detail=str(exc),
                message="Failed to create an execution plan for your request.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error in PLAN stage")
            return AgentResponse.failure(
                error_detail=f"Unexpected error during planning: {exc}",
            )
        plan_secs = time.monotonic() - t0

        logger.info(
            "PLAN stage complete: doc_type=%s, tasks=%d (%.2fs)",
            plan.document_type,
            len(plan.tasks),
            plan_secs,
        )

        # ---- Stage 2: Content Generation ---------------------------------
        t0 = time.monotonic()
        try:
            generated_document = self._content_generator.generate_document(plan)
        except ContentGeneratorAgentError as exc:
            logger.error("Pipeline failed at CONTENT stage: %s", exc)
            return AgentResponse.failure(
                error_detail=str(exc),
                message="Failed to generate document content.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error in CONTENT stage")
            return AgentResponse.failure(
                error_detail=f"Unexpected error during content generation: {exc}",
            )
        content_secs = time.monotonic() - t0

        logger.info(
            "CONTENT stage complete: sections=%d (%.2fs)",
            len(generated_document.sections),
            content_secs,
        )

        # ---- Stage 3: Review ---------------------------------------------
        t0 = time.monotonic()
        try:
            reviewed_document = self._reviewer.review_document(generated_document)
        except ReviewerAgentError as exc:
            logger.error("Pipeline failed at REVIEW stage: %s", exc)
            return AgentResponse.failure(
                error_detail=str(exc),
                message="Failed to review the generated document.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error in REVIEW stage")
            return AgentResponse.failure(
                error_detail=f"Unexpected error during review: {exc}",
            )
        review_secs = time.monotonic() - t0

        logger.info(
            "REVIEW stage complete: issues=%d, revised=%d, clean=%s (%.2fs)",
            len(reviewed_document.report.issues_found),
            len(reviewed_document.report.sections_revised),
            reviewed_document.report.passed_without_changes,
            review_secs,
        )

        # ---- Stage 4: DOCX Generation ------------------------------------
        t0 = time.monotonic()
        try:
            file_path = self._doc_generator.generate_docx(reviewed_document)
        except DocumentGeneratorAgentError as exc:
            logger.error("Pipeline failed at DOCX stage: %s", exc)
            return AgentResponse.failure(
                error_detail=str(exc),
                message="Failed to write the final .docx file.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error in DOCX stage")
            return AgentResponse.failure(
                error_detail=f"Unexpected error during document generation: {exc}",
            )
        docx_secs = time.monotonic() - t0

        elapsed = time.monotonic() - start_time
        logger.info("Pipeline complete in %.2fs. Output: %s", elapsed, file_path)

        stage_timings = {
            "planning_secs": round(plan_secs, 2),
            "generation_secs": round(content_secs, 2),
            "review_secs": round(review_secs, 2),
            "docx_secs": round(docx_secs, 2),
        }

        # ---- Build response ----------------------------------------------
        unresolved_sections = [
            issue.section_name
            for issue in reviewed_document.report.issues_found
            if issue.section_name not in reviewed_document.report.sections_revised
        ]

        if unresolved_sections:
            return self._build_partial_success_response(
                file_path, plan, unresolved_sections, elapsed, stage_timings
            )

        return self._build_success_response(file_path, plan, elapsed, stage_timings)

    # ------------------------------------------------------------------
    # PRIVATE RESPONSE BUILDERS — PURE PYTHON
    # ------------------------------------------------------------------
    def _build_success_response(
        self,
        file_path: str,
        plan,
        elapsed_seconds: float,
        stage_timings: dict,
    ) -> AgentResponse:
        """

        Build a clean-success AgentResponse from the completed pipeline.
        """
        return AgentResponse(
            status=RequestStatus.SUCCESS,
            message=(
                f"Document generated and reviewed successfully in "
                f"{elapsed_seconds:.1f}s. {len(plan.tasks)} sections produced."
            ),
            file_path=file_path,
            plan_summary=self._build_plan_summary(plan, stage_timings),
        )

    def _build_partial_success_response(
        self,
        file_path: str,
        plan,
        unresolved_sections: list,
        elapsed_seconds: float,
        stage_timings: dict,
    ) -> AgentResponse:
        """

        Build a partial-success response for documents where the reviewer
        flagged some sections but could not fully resolve them.
        """
        unresolved_str = ", ".join(f"'{s}'" for s in unresolved_sections)
        return AgentResponse(
            status=RequestStatus.PARTIAL_SUCCESS,
            message=(
                f"Document generated in {elapsed_seconds:.1f}s but the following "
                f"sections could not be fully revised: {unresolved_str}."
            ),
            file_path=file_path,
            plan_summary=self._build_plan_summary(plan, stage_timings),
        )

    @staticmethod
    def _build_plan_summary(plan, stage_timings: dict | None = None) -> dict:
        """

        Convert a SimplifiedExecutionPlan into a plain dict for the
        AgentResponse payload. Includes per-stage timing when provided.
        """
        return {
            "document_type": plan.document_type,
            "total_sections": len(plan.tasks),
            "stage_timings": stage_timings or {},
            "sections": [
                {
                    "section_name": task.section_name,
                    "order": task.order,
                    "final_status": "approved",
                    "was_regenerated": False,
                }
                for task in sorted(plan.tasks, key=lambda t: t.order)
            ],
            "assumptions_made": [
                {
                    "field": field_name,
                    "value": assumption.value,
                    "reasoning": assumption.reasoning,
                }
                for field_name, assumption in plan.assumptions.items()
            ],
        }
