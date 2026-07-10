"""
agents/planner.py

The Planner Agent: turns a raw user request into a structured,
machine-executable ExecutionPlan.

Architecture (matches the approved call-tree exactly):

    PlannerAgent
    │
    ├── normalize_request()           
    ├── classify_document()            
    ├── load_template()               
    ├── extract_information()          
    │       └── fallback_extract()     
    ├── detect_missing_fields()       
    ├── generate_assumptions()         
    ├── merge_fields()                 
    ├── create_tasks()                 
    └── build_execution_plan()       


"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Set

from llm.llm_client import GeminiClient, LLMClientError
from llm.prompts import PromptBuilder
from models.planner_models import (
    Assumption,
    PlannedTask,
    SimplifiedExecutionPlan as ExecutionPlan,
)
from templates.document_templates import (
    DocumentTemplate,
    get_all_document_type_names,
    get_template,
)

logger = logging.getLogger(__name__)


class PlannerAgentError(Exception):
    """Raised when the Planner cannot produce a valid execution plan."""


class PlannerAgent:
    """
    Single Responsibility: raw request in -> validated ExecutionPlan out.

    Does not write content. Does not touch DOCX. Does not review anything.
    """

    def __init__(self, llm_client: GeminiClient) -> None:
        self._llm = llm_client

    # ------------------------------------------------------------------
    # PUBLIC ENTRYPOINT
    # ------------------------------------------------------------------
    def create_plan(self, user_request: str) -> ExecutionPlan:
        """
        Orchestrates all planner sub-steps, in tree order, and returns a
        fully assembled ExecutionPlan.

        """
        normalized_request = self.normalize_request(user_request)

        document_type = self.classify_document(normalized_request)
        template = self.load_template(document_type)

        extracted_fields = self.extract_information(normalized_request, template)

        missing_required = self.detect_missing_fields(template, extracted_fields)

        assumptions: Dict[str, Assumption] = {}
        if missing_required:
            assumptions = self.generate_assumptions(
                document_type, missing_required, extracted_fields
            )

        merged_fields = self.merge_fields(extracted_fields, assumptions)

        tasks = self.create_tasks(template, merged_fields)

        plan = self.build_execution_plan(
            user_request, document_type, merged_fields, assumptions, tasks
        )

        logger.info(
            "Plan created: type=%s, tasks=%d, assumptions=%d",
            document_type,
            len(tasks),
            len(assumptions),
        )
        return plan

    # ------------------------------------------------------------------
    # 1. normalize_request — PURE PYTHON
    # ------------------------------------------------------------------
    def normalize_request(self, user_request: str) -> str:
        """

        Normalizes the raw request: trims whitespace, collapses internal
        newlines/whitespace runs, and enforces a minimum non-empty length.
        """
        normalized = " ".join(user_request.strip().split())
        if not normalized:
            raise PlannerAgentError("User request is empty after normalization.")
        return normalized

    # ------------------------------------------------------------------
    # 2. classify_document — GEMINI
    # ------------------------------------------------------------------
    def classify_document(self, normalized_request: str) -> str:
        """


        Classifies the request into one of the document types defined
        in templates/document_templates.py.

        """
        valid_types = get_all_document_type_names()
        prompt = PromptBuilder.intent_classification(normalized_request, valid_types)

        try:
            result = self._llm.generate_json(prompt)
        except LLMClientError as exc:
            logger.error("Document classification failed: %s", exc)
            raise PlannerAgentError(f"Could not classify document type: {exc}") from exc

        document_type = result.get("document_type", "").strip()

    
        # not in our template registry, fall back deterministically.
        if document_type not in valid_types:
            logger.warning(
                "Gemini returned unknown document_type=%r, falling back to Generic Report",
                document_type,
            )
            document_type = "Generic Report"

        return document_type

    
    # 3. load_template — PURE PYTHON

    def load_template(self, document_type: str) -> DocumentTemplate:
        """
    

        Loads the deterministic template (required fields, optional
        fields, section list) for the classified document type.

        """
        return get_template(document_type)

    
    # 4. extract_information — PYTHON FIRST, GEMINI ONLY IF NEEDED
    
    def extract_information(
        self, normalized_request: str, template: DocumentTemplate
    ) -> Dict[str, str]:
        """
       

        Extracts whatever field values (topic, audience, deadlines, etc.)
        are already present in the request, using cheap, deterministic
        pattern matching FIRST. Only calls Gemini (`fallback_extract`)
        for the specific required fields that Python's heuristics could
        not find.

        """
        valid_field_names = list(template.required_fields) + list(template.optional_fields)

        # --- Python heuristic pass -------------------------------------
        extracted_fields = self._heuristic_field_extraction(
            normalized_request, valid_field_names
        )

        # deterministic pass.
        still_missing_required = [
            field
            for field in template.required_fields
            if field not in extracted_fields
        ]

        if still_missing_required:
            fallback_fields = self.fallback_extract(
                normalized_request, still_missing_required, valid_field_names
            )
            
            # fallback only fills genuine gaps.
            for key, value in fallback_fields.items():
                extracted_fields.setdefault(key, value)

        return extracted_fields

    def _heuristic_field_extraction(
        self, normalized_request: str, field_names: List[str]
    ) -> Dict[str, str]:
        """
       

        Deterministic first pass at field extraction using simple,
        explainable patterns:
          - "<field>: <value>" or "<field> is <value>" style mentions
          - "for the <value>" / "for <value>" as an audience hint when
            the field name is "audience"
          - "by <value>" / "due <value>" as a deadline hint when the
            field name is "deadline" or "due_date"

        """
        found: Dict[str, str] = {}
        lowered = normalized_request.lower()

        for field in field_names:
            field_label = field.replace("_", " ")

            # Pattern: "field: value" or "field - value" or "field is value"
            pattern = rf"{re.escape(field_label)}\s*(?:[:\-]|is)\s*([^.,;]+)"
            match = re.search(pattern, lowered)
            if match:
                value = match.group(1).strip(" .")
                if value:
                    found[field] = value
                    continue

            # Targeted heuristics for common, well-known field names.
            if field == "audience":
                aud_match = re.search(r"for (?:the |our )?([a-z0-9 ]+? team)", lowered)
                if not aud_match:
                    aud_match = re.search(r"for (?:the |our )?([a-z0-9]+ audience)", lowered)
                if aud_match:
                    found[field] = aud_match.group(1).strip()
                    continue

            if field in ("deadline", "due_date"):
                date_match = re.search(
                    r"(?:by|due|before)\s+([a-z]+ \d{1,2}(?:st|nd|rd|th)?"
                    r"(?:,? \d{4})?|\d{1,2}/\d{1,2}(?:/\d{2,4})?)",
                    lowered,
                )
                if date_match:
                    found[field] = date_match.group(1).strip()
                    continue

        return found

    def fallback_extract(
        self,
        normalized_request: str,
        missing_fields: List[str],
        all_field_names: List[str],
    ) -> Dict[str, str]:
        """

        Attempts semantic, paraphrase-aware extraction for the specific
        fields the deterministic pass in `extract_information` could not
        resolve.

        """
        prompt = PromptBuilder.information_extraction(
            normalized_request,
            missing_fields,
            [],
        )

        try:
            result = self._llm.generate_json(prompt)
        except LLMClientError as exc:
            # detect_missing_fields -> generate_assumptions downstream.
            logger.warning("Fallback extraction failed, leaving fields missing: %s", exc)
            return {}

        raw_fields = result.get("extracted_fields", {})

        # for, and that belong to this template's schema.
        valid_field_names = set(all_field_names)
        cleaned_fields = {
            key: value
            for key, value in raw_fields.items()
            if key in valid_field_names
            and key in missing_fields
            and str(value).strip()
        }
        return cleaned_fields


    # 5. detect_missing_fields — PURE PYTHON

    def detect_missing_fields(
        self, template: DocumentTemplate, extracted_fields: Dict[str, str]
    ) -> List[str]:
        """
        

        Computes which required fields were NOT found by extraction
        (heuristic pass + fallback combined).

        """
        required: Set[str] = set(template.required_fields)
        found: Set[str] = set(extracted_fields.keys())
        missing = sorted(required - found)
        if missing:
            logger.info("Missing required fields detected: %s", missing)
        return missing

    
    # 6. generate_assumptions — GEMINI (conditional)
   
    def generate_assumptions(
        self,
        document_type: str,
        missing_fields: List[str],
        known_fields: Dict[str, str],
    ) -> Dict[str, Assumption]:
       
    
        prompt = PromptBuilder.assumption_generation(
            document_type, missing_fields, known_fields
        )

        try:
            result = self._llm.generate_json(prompt)
        except LLMClientError as exc:
            logger.error("Assumption generation failed: %s", exc)
            raise PlannerAgentError(f"Could not generate assumptions: {exc}") from exc

        raw_assumptions = result.get("assumptions", {})

        # asked about. Deterministic filtering again.
        assumptions: Dict[str, Assumption] = {}
        for field in missing_fields:
            entry = raw_assumptions.get(field)
            if entry and isinstance(entry, dict) and entry.get("value"):
                assumptions[field] = Assumption(
                    field_name=field,
                    value=str(entry["value"]),
                    reasoning=str(entry.get("reasoning", "")),
                )
            else:
              
                # leaving the plan incomplete or making another API call.
                logger.warning(
                    "Gemini did not provide assumption for field=%r, using generic fallback",
                    field,
                )
                assumptions[field] = Assumption(
                    field_name=field,
                    value="Not specified",
                    reasoning="Fallback default — Gemini did not supply this field.",
                )

        return assumptions

    # 7. merge_fields — PURE PYTHON

    def merge_fields(
        self,
        extracted_fields: Dict[str, str],
        assumptions: Dict[str, Assumption],
    ) -> Dict[str, str]:
        """
 

        Merges extracted fields with assumption values into a single
        flat dict for downstream use.


        """
        merged = dict(extracted_fields)
        for field_name, assumption in assumptions.items():
            merged[field_name] = assumption.value
        return merged

   
    # 8. create_tasks — PURE PYTHON

    def create_tasks(
        self,
        template: DocumentTemplate,
        known_fields: Dict[str, str],
    ) -> List[PlannedTask]:
        """
       

        Produces the ordered TODO list of section-writing tasks directly
        from the template's section list.

       """
        tasks: List[PlannedTask] = []
        for order, section in enumerate(template.sections, start=1):
            tasks.append(
                PlannedTask(
                    section_name=section.name,
                    order=order,
                    intent=section.guidance
                    + f" Known context: {', '.join(sorted(known_fields.keys())) or 'none provided'}.",
                )
            )
        return tasks

    
    # 9. build_execution_plan — PURE PYTHON
 
    def build_execution_plan(
        self,
        original_request: str,
        document_type: str,
        known_fields: Dict[str, str],
        assumptions: Dict[str, Assumption],
        tasks: List[PlannedTask],
    ) -> ExecutionPlan:
        """
    

        Final assembly step: packages every previously computed piece
        (document type, merged fields, assumptions, tasks) into a single
        validated ExecutionPlan object.

        """
        return ExecutionPlan(
            original_request=original_request,
            document_type=document_type,
            known_fields=known_fields,
            assumptions=assumptions,
            tasks=tasks,
        )