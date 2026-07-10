"""
models/request.py

Defines the input contract for POST /agent.

This is the FIRST validation gate the raw HTTP body passes through.
All checks here are deterministic (length, emptiness, whitespace) —
per the hybrid-architecture rule, Python handles this, not Gemini.
A request that fails validation here never reaches the Orchestrator.
"""

from pydantic import BaseModel, Field, field_validator

from config import settings


class AgentRequest(BaseModel):
    """
    Input schema for POST /agent.

    Example:
        {
            "request": "Create a business proposal for a SaaS startup
                         targeting small e-commerce businesses"
        }

    Attributes:
        request: The user's natural-language instruction describing
            what document they want generated. This raw string is what
            the Planner's Request Analyzer will process later.
    """

    request: str = Field(
        ...,
        min_length=1,
        description="Natural-language description of the document the "
                    "user wants generated (e.g. 'Create a project plan "
                    "for migrating our backend to microservices').",
        examples=[
            "Create a business proposal for a SaaS startup targeting "
            "small e-commerce businesses"
        ],
    )

    @field_validator("request")
    @classmethod
    def validate_request_not_blank(cls, value: str) -> str:
        """
        Reject whitespace-only input.

        min_length=1 alone would still accept a string of pure spaces
        (e.g. "   "), which is meaningless input that would otherwise
        propagate all the way into a Gemini prompt before failing.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError(
                "`request` cannot be empty or whitespace-only. "
                "Provide a description of the document you want generated."
            )
        return stripped

    @field_validator("request")
    @classmethod
    def validate_request_length(cls, value: str) -> str:
        """
        Enforce an upper bound on request length.

        This protects two things at once: it prevents abusive/oversized
        payloads from reaching the system, and it caps how large a
        prompt the Planner will eventually pass to Gemini (cost and
        latency control). The limit is centralized in config.py so it
        can be tuned without touching this file.
        """
        max_length = settings.max_request_length
        if len(value) > max_length:
            raise ValueError(
                f"`request` exceeds maximum allowed length of "
                f"{max_length} characters (received {len(value)}). "
                f"Please shorten your request."
            )
        return value

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "request": "Create a project plan for migrating our "
                               "backend to a microservices architecture"
                }
            ]
        }
    }