"""
agents/content_generator.py

The Content Generator Agent: takes the ExecutionPlan produced by
PlannerAgent (an ordered list of PlannedTasks) and turns it into
actual written section content.

Call tree (same hybrid-architecture discipline as agents/planner.py):

    ContentGeneratorAgent
    │
    ├── generate_document()             
    │       │
    │       ├── build_section_context() 
    │       ├── generate_section_content() 
    │       ├── sanitize_content()      
    │       └── validate_section_content() 
    │
    └── assemble_generated_document()   
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from llm.llm_client import GeminiClient, LLMClientError
from llm.prompts import PromptBuilder
from models.planner_models import ExecutionPlan, PlannedTask

logger = logging.getLogger(__name__)
MIN_SECTION_CONTENT_LENGTH = 40


class ContentGeneratorAgentError(Exception):
    """Raised when the Content Generator cannot produce valid section content."""


@dataclass
class GeneratedSection:
    """
    Plain data container for one written section.
    """

    section_name: str
    order: int
    content: str
    word_count: int = field(default=0)


@dataclass
class GeneratedDocument:
    """
    Full set of generated sections for one ExecutionPlan, still in
    template order, ready to be handed to ReviewerAgent and then
    DocumentGeneratorAgent.
    """

    document_type: str
    original_request: str
    sections: List[GeneratedSection]


class ContentGeneratorAgent:
    """
    Single Responsibility: ExecutionPlan in -> GeneratedDocument out.
    """

    def __init__(self, llm_client: GeminiClient) -> None:
        self._llm = llm_client

   
    # PUBLIC ENTRYPOINT
    def generate_document(self, plan: ExecutionPlan) -> GeneratedDocument:
        
        generated_sections: List[GeneratedSection] = []
        prior_sections_summary: Dict[str, str] = {}

        for task in sorted(plan.tasks, key=lambda t: t.order):
            context = self.build_section_context(plan, task, prior_sections_summary)

            try:
                raw_content = self.generate_section_content(
                    plan.document_type, task, context
                )
            except LLMClientError as exc:
                logger.error(
                    "Content generation failed for section=%r: %s",
                    task.section_name,
                    exc,
                )
                raise ContentGeneratorAgentError(
                    f"Could not generate content for section '{task.section_name}': {exc}"
                ) from exc

            cleaned_content = self.sanitize_content(raw_content)
            validated_content = self.validate_section_content(
                task.section_name, cleaned_content
            )

            section = GeneratedSection(
                section_name=task.section_name,
                order=task.order,
                content=validated_content,
                word_count=len(validated_content.split()),
            )
            generated_sections.append(section)

    
            prior_sections_summary[task.section_name] = self._summarize_for_context(
                validated_content
            )

        document = self.assemble_generated_document(plan, generated_sections)

        logger.info(
            "Document generated: type=%s, sections=%d, total_words=%d",
            plan.document_type,
            len(generated_sections),
            sum(s.word_count for s in generated_sections),
        )
        return document

   
    # build_section_context — PURE PYTHON
   
    def build_section_context(
        self,
        plan: ExecutionPlan,
        task: PlannedTask,
        prior_sections_summary: Dict[str, str],
    ) -> Dict[str, Any]:
        return {
            "section_name": task.section_name,
            "section_intent": task.intent,
            "known_fields": dict(plan.known_fields),
            "prior_sections_summary": dict(prior_sections_summary),
        }

  
    # generate_section_content — GEMINI
    def generate_section_content(
        self,
        document_type: str,
        task: PlannedTask,
        context: Dict[str, Any],
    ) -> str:
        prompt = PromptBuilder.section_content_generation(
            document_type=document_type,
            section_name=task.section_name,
            section_intent=task.intent,
            known_fields=context["known_fields"],
            prior_sections_summary=context["prior_sections_summary"],
        )

        result = self._llm.generate_text(prompt)
        return result

    # sanitize_content 
    def sanitize_content(self, raw_content: str) -> str:
        content = raw_content.strip()
        content = re.sub(r"^#{1,6}\s*[^\n]+\n+", "", content, count=1)
        content = re.sub(r"^```[a-zA-Z]*\n", "", content)
        content = re.sub(r"\n```$", "", content)
        content = re.sub(r"\n{3,}", "\n\n", content)

        return content.strip()

   
    # validate_section_content 
    def validate_section_content(self, section_name: str, content: str) -> str:
        if not content or len(content) < MIN_SECTION_CONTENT_LENGTH:
            logger.error(
                "Generated content for section=%r is missing or too short (%d chars)",
                section_name,
                len(content),
            )
            raise ContentGeneratorAgentError(
                f"Generated content for section '{section_name}' is empty or too short."
            )
        return content

    def _summarize_for_context(self, content: str, max_chars: int = 220) -> str:
        if len(content) <= max_chars:
            return content
        return content[:max_chars].rsplit(" ", 1)[0] + "..."

    # assemble_generated_document — PURE PYTHON
    def assemble_generated_document(
        self,
        plan: ExecutionPlan,
        generated_sections: List[GeneratedSection],
    ) -> GeneratedDocument:
        return GeneratedDocument(
            document_type=plan.document_type,
            original_request=plan.original_request,
            sections=sorted(generated_sections, key=lambda s: s.order),
        )