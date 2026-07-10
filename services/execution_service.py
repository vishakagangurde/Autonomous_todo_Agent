"""
services/execution_service.py

Service layer for execution plan management and task tracking.

Provides utilities for inspecting, persisting, and querying the state
of pipeline execution plans. This service is consumed by monitoring
endpoints and by the Orchestrator for plan introspection.


"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import settings

logger = logging.getLogger(__name__)

# Sub-directory within output_dir where plan JSON summaries are stored.
# Keeping plans alongside outputs makes them easy to correlate when debugging.
PLANS_SUBDIR = "plans"


class ExecutionService:
    """
    Service for execution plan persistence and introspection.

    Provides methods to:
        - Save a plan summary to disk alongside the generated .docx.
        - Load a previously saved plan summary by ID.
        - List all saved plan summaries in the output directory.

    Why save plans to disk: gives the API an audit trail of what the
    system decided for each request — useful for debugging and for
    demonstrating the autonomous planning behaviour to evaluators.
    """

    def __init__(self) -> None:
        """Resolve and ensure the plans sub-directory exists."""
        self._plans_dir = settings.output_dir / PLANS_SUBDIR
        self._plans_dir.mkdir(parents=True, exist_ok=True)

    # PLAN PERSISTENCE
    def save_plan_summary(
        self,
        plan_dict: Dict[str, Any],
        document_type: str,
    ) -> str:
        """
        Serialize and save a plan summary dict to a JSON file.

        Args:
            plan_dict: The plain dict representation of the plan
                (e.g. as returned by OrchestratorAgent._build_plan_summary).
            document_type: Used to generate a human-readable filename.

        Returns:
            The relative path to the saved plan JSON file.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_type = document_type.replace(" ", "_").replace("/", "_").lower()
        filename = f"plan_{safe_type}_{timestamp}.json"
        file_path = self._plans_dir / filename

        plan_record = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "document_type": document_type,
            "plan": plan_dict,
        }

        try:
            file_path.write_text(
                json.dumps(plan_record, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("Plan summary saved to: %s", file_path)
        except OSError as exc:
            logger.warning("Could not save plan summary to %s: %s", file_path, exc)
            return ""

        return str(settings.output_dir / PLANS_SUBDIR / filename)

    def load_plan_summary(self, plan_filename: str) -> Optional[Dict[str, Any]]:
        """
        Load a previously saved plan summary by its filename.

        Args:
            plan_filename: Basename of the plan JSON file (e.g.
                "plan_business_proposal_20260706_143012.json").

        Returns:
            The parsed plan dict, or None if the file is not found or
            cannot be parsed.
        """
        file_path = self._plans_dir / plan_filename

        if not file_path.exists():
            logger.warning("Plan file not found: %s", file_path)
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
            return json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load plan from %s: %s", file_path, exc)
            return None

    # ------------------------------------------------------------------
    # PLAN LISTING
    # ------------------------------------------------------------------
    def list_saved_plans(self) -> List[Dict[str, Any]]:
        """
        List metadata for all saved plan summaries.

        Returns a list of dicts, each containing at minimum:
            - filename: str
            - saved_at: str (ISO-8601)
            - document_type: str

        Sorted newest-first by filename (which embeds a timestamp).
        Pure Python — no Gemini call.
        """
        plans: List[Dict[str, Any]] = []

        if not self._plans_dir.exists():
            return plans

        for plan_file in sorted(self._plans_dir.glob("plan_*.json"), reverse=True):
            try:
                content = json.loads(plan_file.read_text(encoding="utf-8"))
                plans.append(
                    {
                        "filename": plan_file.name,
                        "saved_at": content.get("saved_at", ""),
                        "document_type": content.get("document_type", "unknown"),
                    }
                )
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipping unreadable plan file %s: %s", plan_file.name, exc)
                continue

        return plans

    # ------------------------------------------------------------------
    # TASK PROGRESS UTILITIES
    # ------------------------------------------------------------------
    @staticmethod
    def summarize_task_progress(tasks: List[Any]) -> Dict[str, int]:
        """
        Return a count breakdown of tasks by status.

        Args:
            tasks: A list of PlannedTask or Task objects. Must have a
                `section_name` attribute; status is optional (counted as
                "unknown" if absent).

        Returns:
            Dict mapping status label to count, e.g.:
                {"completed": 5, "pending": 0, "failed": 0, "total": 5}
        """
        counts: Dict[str, int] = {"total": len(tasks)}

        for task in tasks:
            status = getattr(task, "status", "planned")
            status_str = status.value if hasattr(status, "value") else str(status)
            counts[status_str] = counts.get(status_str, 0) + 1

        return counts
