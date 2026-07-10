"""
agents/reviewer.py

The Reviewer Agent: takes the GeneratedDocument produced by
ContentGeneratorAgent and checks it for completeness, leaked
placeholders, and genuine quality/consistency issues — revising only
what actually needs revising.

Call tree (same hybrid-architecture discipline as planner.py /
content_generator.py):

    ReviewerAgent
    │
    ├── review_document()                 +
    │       │
    │       ├── check_section_completeness() 
    │       ├── check_placeholder_leakage()   
    │       ├── evaluate_content_quality()     
    │       └── revise_flagged_sections()     
    │
    └── compile_review_report()            
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from agents.content_generator import GeneratedDocument, GeneratedSection
from llm.llm_client import GeminiClient, LLMClientError
from llm.prompts import PromptBuilder

logger = logging.getLogger(__name__)

# Deterministic red flags: if any of these leak into final content, the
# section is broken regardless of what an LLM "thinks" of its quality.
PLACEHOLDER_PATTERNS = [
    r"\[.*?\]",              # "[insert X here]", "[TODO]", "[audience]"
    r"\bTODO\b",
    r"\bTBD\b",
    r"\blorem ipsum\b",
    r"<.*?>",                # stray angle-bracket placeholders
]

MIN_ACCEPTABLE_QUALITY_SCORE = 6  # out of 10, Gemini-assigned


class ReviewerAgentError(Exception):
    """Raised when the Reviewer cannot produce a valid review."""


@dataclass
class ReviewIssue:
    """One flagged problem with one section."""

    section_name: str
    issue_type: str          # "missing" | "placeholder_leak" | "quality"
    description: str
    severity: str = "medium"  # "low" | "medium" | "high"


@dataclass
class ReviewReport:
    """Full record of what was checked and what (if anything) was fixed."""

    issues_found: List[ReviewIssue]
    sections_revised: List[str]
    passed_without_changes: bool


@dataclass
class ReviewedDocument:
    """The (possibly revised) document, plus the report explaining why."""

    document_type: str
    original_request: str
    sections: List[GeneratedSection]
    report: ReviewReport


class ReviewerAgent:
    """
    Single Responsibility: GeneratedDocument in -> ReviewedDocument out.

    Does not decide structure (PlannerAgent's job).
    Does not do first-draft writing (ContentGeneratorAgent's job).
    Does not touch DOCX (DocumentGeneratorAgent's job).
    """

    def __init__(self, llm_client: GeminiClient) -> None:
        self._llm = llm_client

    # ------------------------------------------------------------------
    # PUBLIC ENTRYPOINT
    # ------------------------------------------------------------------
    def review_document(self, document: GeneratedDocument) -> ReviewedDocument:
        """
       

        Runs checks in increasing cost order — cheap deterministic
        checks first, expensive LLM judgment only where warranted, and
        LLM-driven revision only for sections actually flagged.

       
        """
        issues: List[ReviewIssue] = []

        completeness_issues = self.check_section_completeness(document)
        issues.extend(completeness_issues)

        placeholder_issues = self.check_placeholder_leakage(document)
        issues.extend(placeholder_issues)

        quality_issues = self.evaluate_content_quality(document)
        issues.extend(quality_issues)

        sections_by_name: Dict[str, GeneratedSection] = {
            s.section_name: s for s in document.sections
        }

       
        # document, and never when nothing was flagged.
        flagged_sections = sorted(
            {issue.section_name for issue in issues if issue.section_name in sections_by_name}
        )

        sections_revised: List[str] = []
        if flagged_sections:
            revised_sections = self.revise_flagged_sections(
                document, flagged_sections, issues
            )
            for section_name, new_content in revised_sections.items():
                sections_by_name[section_name].content = new_content
                sections_by_name[section_name].word_count = len(new_content.split())
                sections_revised.append(section_name)

        report = self.compile_review_report(issues, sections_revised)

        reviewed = ReviewedDocument(
            document_type=document.document_type,
            original_request=document.original_request,
            sections=sorted(sections_by_name.values(), key=lambda s: s.order),
            report=report,
        )

        logger.info(
            "Review complete: issues=%d, sections_revised=%d, clean=%s",
            len(issues),
            len(sections_revised),
            report.passed_without_changes,
        )
        return reviewed

   
    # check_section_completeness — PURE PYTHON
   
    def check_section_completeness(
        self, document: GeneratedDocument
    ) -> List[ReviewIssue]:
        """
       

        Flags any section that is missing entirely or empty after
        whitespace stripping.

        """
        issues: List[ReviewIssue] = []
        for section in document.sections:
            if not section.content or not section.content.strip():
                issues.append(
                    ReviewIssue(
                        section_name=section.section_name,
                        issue_type="missing",
                        description="Section content is empty.",
                        severity="high",
                    )
                )
        return issues

    
    # check_placeholder_leakage — PURE PYTHON
    
    def check_placeholder_leakage(
        self, document: GeneratedDocument
    ) -> List[ReviewIssue]:
        """
     
        Scans each section for known placeholder patterns
        (`[TODO]`, `TBD`, `Lorem ipsum`, stray `<...>` tags) that
        sometimes leak through from generation.

        """
        issues: List[ReviewIssue] = []
        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in PLACEHOLDER_PATTERNS]

        for section in document.sections:
            for pattern in compiled_patterns:
                match = pattern.search(section.content)
                if match:
                    issues.append(
                        ReviewIssue(
                            section_name=section.section_name,
                            issue_type="placeholder_leak",
                            description=f"Leaked placeholder text detected: {match.group(0)!r}",
                            severity="high",
                        )
                    )
                    break  # one flag per section is enough to trigger revision
        return issues

    
    # evaluate_content_quality — GEMINI
  
    def evaluate_content_quality(
        self, document: GeneratedDocument
    ) -> List[ReviewIssue]:
        """
        

        Judges things Python structurally cannot: tone consistency
        across sections, whether a section actually delivers on its
        stated intent, redundancy between sections, and overall
        professional quality. Returns a numeric score (0-10) and a
        short reason per section.

        """
        section_payload = {s.section_name: s.content for s in document.sections}
        prompt = PromptBuilder.quality_review(document.document_type, section_payload)

        try:
            result = self._llm.generate_json(prompt)
        except LLMClientError as exc:
           
            # pipeline on a review-step outage.
            logger.warning("Quality evaluation failed, skipping semantic review: %s", exc)
            return []

        raw_scores = result.get("section_scores", {})
        valid_section_names = {s.section_name for s in document.sections}

        issues: List[ReviewIssue] = []
        for section_name, entry in raw_scores.items():
            # PYTHON SAFETY NET: ignore any section name Gemini
            # hallucinated that isn't actually in this document.
            if section_name not in valid_section_names:
                continue
            if not isinstance(entry, dict):
                continue

            score = entry.get("score")
            reason = str(entry.get("reason", "")).strip()
            try:
                score = int(score)
            except (TypeError, ValueError):
                continue

            if score < MIN_ACCEPTABLE_QUALITY_SCORE:
                issues.append(
                    ReviewIssue(
                        section_name=section_name,
                        issue_type="quality",
                        description=reason or f"Quality score {score} below threshold.",
                        severity="medium",
                    )
                )
        return issues

    
    # revise_flagged_sections — GEMINI (conditional)
    
    def revise_flagged_sections(
        self,
        document: GeneratedDocument,
        flagged_section_names: List[str],
        issues: List[ReviewIssue],
    ) -> Dict[str, str]:
        """
       

        Note the control flow in `review_document`: this is only invoked
        `if flagged_sections:` — Python decides WHETHER any revision
        call happens at all, and WHICH sections it covers. A clean
        document never triggers this method.

       
        """
        sections_by_name = {s.section_name: s for s in document.sections}
        issues_by_section: Dict[str, List[str]] = {}
        for issue in issues:
            issues_by_section.setdefault(issue.section_name, []).append(issue.description)

        revised: Dict[str, str] = {}
        for section_name in flagged_section_names:
            section = sections_by_name.get(section_name)
            if section is None:
                continue

            prompt = PromptBuilder.section_revision(
                document_type=document.document_type,
                section_name=section_name,
                original_content=section.content,
                issues=issues_by_section.get(section_name, []),
            )

            try:
                new_content = self._llm.generate_text(prompt)
            except LLMClientError as exc:
                logger.warning(
                    "Revision failed for section=%r, keeping original content: %s",
                    section_name,
                    exc,
                )
                continue

            cleaned = new_content.strip()
            
            # original in that case rather than downgrading the doc.
            if cleaned and len(cleaned) >= len(section.content) * 0.5:
                revised[section_name] = cleaned
            else:
                logger.warning(
                    "Revision for section=%r rejected as too short, keeping original",
                    section_name,
                )

        return revised

 
    # compile_review_report — PURE PYTHON
  
    def compile_review_report(
        self,
        issues: List[ReviewIssue],
        sections_revised: List[str],
    ) -> ReviewReport:
        """


        Packages the issues found and sections revised into a single
        ReviewReport for downstream logging/auditing/API response.

    
        """
        return ReviewReport(
            issues_found=issues,
            sections_revised=sections_revised,
            passed_without_changes=(len(issues) == 0),
        )