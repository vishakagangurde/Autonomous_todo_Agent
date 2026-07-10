"""
llm/prompts.py

Centralized prompt builder for all Gemini calls in the pipeline.

Design rule: every string that crosses the Python <-> Gemini boundary
lives here. No agent module hard-codes a prompt. This makes the system's
Gemini usage reviewable, testable, and auditable from one file.

"""

from __future__ import annotations

import json
from typing import Any, Dict, List


class PromptBuilder:
    """
    Static factory for every prompt sent to Gemini.

    All methods return a plain string ready to pass directly to
    GeminiClient.generate_json() or GeminiClient.generate_text().
    No Gemini logic lives here — this is pure Python string construction.
    """

    # 1. Intent Classification  (PlannerAgent.classify_document)

    @staticmethod
    def intent_classification(
        user_request: str,
        valid_document_types: List[str],
    ) -> str:
        """
        Prompt Gemini to pick the single best document type for a request.

        The valid_document_types list is Python-owned (from
        templates/document_templates.py) so Gemini cannot hallucinate a
        type we don't support — it can only select from the closed set
        we provide.

        Expected JSON response shape:
            {"document_type": "<one of the listed types>"}
        """
        types_str = "\n".join(f"  - {t}" for t in valid_document_types)
        return f"""You are a document-type classifier. Given the user request below,
identify the single most appropriate document type from the list provided.

Valid document types:
{types_str}

User request:
\"\"\"{user_request}\"\"\"

Rules:
1. Return ONLY valid JSON with this exact structure: {{"document_type": "<type>"}}
2. The value MUST be one of the listed document types — no variations or synonyms.
3. If the request does not clearly match any type, choose the closest one; never invent a new type.
4. Do NOT include markdown fences, explanations, or any text outside the JSON object.

JSON response:"""


    # 2. Information Extraction  (PlannerAgent.fallback_extract)
  
    @staticmethod
    def information_extraction(
        user_request: str,
        missing_fields: List[str],
        known_fields: List[str],
    ) -> str:
        """
        Prompt Gemini to extract specific field values from the request.

        Only called for fields Python's heuristic pass could NOT find.
        The field list comes from the Python-owned template schema so
        Gemini cannot introduce fields we don't recognize.

        Expected JSON response shape:
            {
              "extracted_fields": {
                "field_name": "extracted value",
                ...
              }
            }
        """
        fields_str = "\n".join(f"  - {f}" for f in missing_fields)
        already_known = (
            "\n".join(f"  - {f}" for f in known_fields)
            if known_fields
            else "  (none yet)"
        )
        return f"""You are an information extraction assistant. Extract the requested
fields from the user request below.

Fields to extract:
{fields_str}

Already known fields (do NOT re-extract these):
{already_known}

User request:
\"\"\"{user_request}\"\"\"

Rules:
1. Return ONLY valid JSON with this exact structure:
   {{"extracted_fields": {{"field_name": "value", ...}}}}
2. Only include fields from the "Fields to extract" list above.
3. If a field cannot be found or inferred from the request, omit it from the response.
4. Values must be concise strings, not nested objects.
5. Do NOT include markdown fences or any text outside the JSON object.

JSON response:"""

   
    # 3. Assumption Generation  (PlannerAgent.generate_assumptions)
   
    @staticmethod
    def assumption_generation(
        document_type: str,
        missing_fields: List[str],
        known_fields: Dict[str, str],
    ) -> str:
        """
        Prompt Gemini to propose sensible default values for fields the
        user didn't supply.

      

        Expected JSON response shape:
            {
              "assumptions": {
                "field_name": {
                  "value": "assumed value",
                  "reasoning": "short justification"
                },
                ...
              }
            }
        """
        fields_str = "\n".join(f"  - {f}" for f in missing_fields)
        context_str = (
            json.dumps(known_fields, indent=2) if known_fields else "  {}"
        )
        return f"""You are a document planning assistant. A user has requested a
"{document_type}" document but did not supply all required fields.
Propose sensible, professional default values for the missing fields.

Document type: {document_type}

Known context (already supplied by the user):
{context_str}

Fields requiring assumptions:
{fields_str}

Rules:
1. Return ONLY valid JSON with this exact structure:
   {{
     "assumptions": {{
       "field_name": {{
         "value": "assumed value",
         "reasoning": "one-sentence justification"
       }}
     }}
   }}
2. Every field listed under "Fields requiring assumptions" MUST appear in the response.
3. Assumptions should be conservative, professional, and consistent with the known context.
4. "reasoning" must be concise (25 words or fewer).
5. Do NOT include markdown fences or any text outside the JSON object.

JSON response:"""

    # 4. Section Content Generation  (ContentGeneratorAgent.generate_section_content)
    
    @staticmethod
    def section_content_generation(
        document_type: str,
        section_name: str,
        section_intent: str,
        known_fields: Dict[str, Any],
        prior_sections_summary: Dict[str, str],
    ) -> str:
        """
        Prompt Gemini to write the prose for a single document section.

        Returns plain text (not JSON) — the caller uses generate_text().

        The known_fields dict grounds Gemini in the user's actual
        context; prior_sections_summary keeps later sections consistent
        with earlier ones without re-sending the full prior text.
        """
        fields_str = (
            json.dumps(known_fields, indent=2) if known_fields else "  {}"
        )
        prior_str = (
            "\n".join(
                f"  [{name}]: {summary}"
                for name, summary in prior_sections_summary.items()
            )
            if prior_sections_summary
            else "  (this is the first section)"
        )
        return f"""You are a professional business writer. Write the "{section_name}"
section of a {document_type}.

Section intent (what this section must accomplish):
{section_intent}

Document context (known fields):
{fields_str}

Summary of sections already written (for consistency — do NOT repeat their content):
{prior_str}

Writing rules:
1. Write professional, well-structured prose in plain text paragraphs.
2. Do NOT include the section heading/title in your response — it will be added separately.
3. Do NOT use markdown headers (##) or code fences in the body text.
4. Stay focused on this section's intent; do not duplicate content already covered above.
5. Length: 150-350 words is typical; adjust naturally to the section's scope.
6. Write in third-person or neutral register unless the known fields indicate otherwise.

Section content (plain text only):"""

    # 5. Quality Review  (ReviewerAgent.evaluate_content_quality)
 
    @staticmethod
    def quality_review(
        document_type: str,
        sections: Dict[str, str],
    ) -> str:
        """
        Prompt Gemini to score each section for quality and flag issues.

        The sections dict is Python-owned; Gemini can only score sections
        that are actually present — the Python caller filters out any
        section names Gemini hallucinates in the response.

        Expected JSON response shape:
            {
              "section_scores": {
                "Section Name": {
                  "score": <int 0-10>,
                  "reason": "brief explanation"
                },
                ...
              }
            }
        """
        sections_str = "\n\n".join(
            f'--- {name} ---\n{content[:600]}{"..." if len(content) > 600 else ""}'
            for name, content in sections.items()
        )
        section_names = list(sections.keys())
        return f"""You are a professional document reviewer. Score each section of this
{document_type} on a scale of 0-10 for professional quality, relevance, and completeness.

Document sections:
{sections_str}

Scoring guide:
  9-10: Excellent — professional, on-topic, well-structured, no issues.
  7-8:  Good — minor improvements possible but acceptable quality.
  5-6:  Adequate — noticeable issues but usable with light revision.
  0-4:  Poor — significant problems: off-topic, incoherent, placeholder text, too short.

Rules:
1. Return ONLY valid JSON with this exact structure:
   {{
     "section_scores": {{
       "Section Name": {{"score": <int>, "reason": "<20 words max>"}},
       ...
     }}
   }}
2. Score ONLY these section names (use exact spelling):
   {json.dumps(section_names)}
3. "reason" must be 20 words or fewer and actionable (say WHY the score is low if < 7).
4. Do NOT include markdown fences or any text outside the JSON object.

JSON response:"""

    
    # 6. Section Revision  (ReviewerAgent.revise_flagged_sections)
    
    @staticmethod
    def section_revision(
        document_type: str,
        section_name: str,
        original_content: str,
        issues: List[str],
    ) -> str:
        """
        Prompt Gemini to revise a specific section based on identified issues.

        Returns plain text (not JSON) — the caller uses generate_text().

        Gemini is given the original content AND the specific issues to
        fix; it cannot change the section name or restructure other parts
        of the document — only rewrite this one section's prose.
        """
        issues_str = (
            "\n".join(f"  - {issue}" for issue in issues)
            if issues
            else "  - General quality improvement required."
        )
        return f"""You are a professional editor. Revise the "{section_name}" section
of a {document_type} to address the specific issues listed below.

Issues to fix:
{issues_str}

Original section content:
\"\"\"{original_content}\"\"\"

Revision rules:
1. Fix all listed issues while preserving any content that is already correct.
2. Do NOT include the section heading/title in your response.
3. Do NOT use markdown headers or code fences in the body text.
4. The revised section should be at least as long as the original (do not shorten it).
5. Maintain the same professional register as the rest of the document.
6. Return ONLY the revised section prose — no preamble like "Here is the revised section:".

Revised section content:"""
