"""
models/response.py

Defines the output contract for POST /agent.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from utils.constants import DocumentType, RequestStatus
from models.planner_models import Assumption, MissingField, ExecutionPlan


class SectionSummary(BaseModel):
    """
    Lightweight summary of a single generated section, for the response
    payload. Deliberately excludes full section content (kept small —
    the client downloads the .docx for the actual content).
    """

    section_name: str
    was_regenerated: bool = Field(
        default=False,
        description="True if the Review Agent flagged this section for "
                    "regeneration at least once before final approval.",
    )
    final_status: str = Field(
        ..., description="Final SectionStatus value after the review pass."
    )


class PlanSummary(BaseModel):
    """
    Condensed view of the ExecutionPlan's key decisions — this is the
    part of the response that demonstrates autonomous planning to
    whoever is evaluating the API output.
    """

    document_type: DocumentType
    total_sections: int
    missing_fields_detected: list[MissingField] = Field(default_factory=list)
    assumptions_made: list[Assumption] = Field(default_factory=list)
    sections: list[SectionSummary] = Field(default_factory=list)

    @classmethod
    def from_execution_plan(cls, plan: ExecutionPlan) -> "PlanSummary":
        """
        Build a PlanSummary from a completed ExecutionPlan.

        Pure Python transformation — no Gemini call. This is the
        deterministic "reporting" layer over the plan the agents
        already produced.
        """
        section_summaries = [
            SectionSummary(
                section_name=section.section_name,
                was_regenerated=section.regeneration_count > 0,
                final_status=section.review_status.value,
            )
            for section in plan.generated_sections
        ]
        return cls(
            document_type=plan.document_type,
            total_sections=len(plan.tasks),
            missing_fields_detected=plan.missing_fields,
            assumptions_made=plan.assumptions,
            sections=section_summaries,
        )


class AgentResponse(BaseModel):
    """
    Final response body for POST /agent.

    Example:
        {
            "status": "success",
            "message": "Document generated successfully.",
            "file_path": "outputs/business_proposal_20260706_143012.docx",
            "plan_summary": { ... },
            "generated_at": "2026-07-06T14:30:12Z"
        }
    """

    status: RequestStatus = Field(
        ..., description="Overall outcome of the pipeline run."
    )
    message: str = Field(
        ..., description="Human-readable summary of what happened."
    )
    file_path: Optional[str] = Field(
        default=None,
        description="Path to the generated .docx file, relative to the "
                    "server's output directory. None if generation failed "
                    "before the Document Generator stage.",
    )
    plan_summary: Optional[PlanSummary] = Field(
        default=None,
        description="Summary of the Planner's decisions and the Review "
                    "Agent's findings. None if the request failed before "
                    "a plan could be produced.",
    )
    error_detail: Optional[str] = Field(
        default=None,
        description="Present only when status is FAILED — the reason "
                    "the pipeline could not complete.",
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of when this response was constructed.",
    )

    @classmethod
    def success(
        cls, file_path: str, plan: ExecutionPlan, message: Optional[str] = None
    ) -> "AgentResponse":
        """
        Build a successful response from a completed ExecutionPlan.

        Convenience constructor used by the Orchestrator so response-
        building logic doesn't get duplicated/hand-rolled in app.py.
        """
        return cls(
            status=RequestStatus.SUCCESS,
            message=message or "Document generated and reviewed successfully.",
            file_path=file_path,
            plan_summary=PlanSummary.from_execution_plan(plan),
        )

    @classmethod
    def partial_success(
        cls, file_path: str, plan: ExecutionPlan, message: str
    ) -> "AgentResponse":
        """
        Build a response for cases where a document was generated but
        one or more sections could not be fully approved even after
        the maximum regeneration attempts (see
        MAX_REGENERATION_ATTEMPTS_PER_SECTION in constants.py).
        """
        return cls(
            status=RequestStatus.PARTIAL_SUCCESS,
            message=message,
            file_path=file_path,
            plan_summary=PlanSummary.from_execution_plan(plan),
        )

    @classmethod
    def failure(cls, error_detail: str, message: Optional[str] = None) -> "AgentResponse":
        """
        Build a failure response. Used by app.py's exception handlers
        when the pipeline cannot complete at all (e.g. Gemini API
        outage, unrecoverable validation error).
        """
        return cls(
            status=RequestStatus.FAILED,
            message=message or "Document generation failed.",
            error_detail=error_detail,
        )