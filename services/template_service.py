"""
services/template_service.py

Service layer for document template discovery and introspection.

Provides a clean interface for the FastAPI layer to query available
document types and their associated template metadata — without
exposing the internal DocumentTemplate dataclass structure directly.

Design rule: no Gemini calls here. All template data is Python-owned
(in templates/document_templates.py) and returned as plain dicts
suitable for JSON serialization.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from templates.document_templates import (
    DOCUMENT_TEMPLATES,
    DocumentTemplate,
    get_all_document_type_names,
    get_template,
)
from utils.constants import DocumentType

logger = logging.getLogger(__name__)


class TemplateService:
    """
    Read-only service for document template metadata.

    Provides three capabilities:
        1. List all available document types (for the GET /templates endpoint).
        2. Get the full metadata for a specific template.
        3. Check whether a given type string maps to a known template.

    All operations are pure Python lookups — no Gemini call is ever made
    from this service. Template data is static (defined at import time
    in document_templates.py) and therefore safe to return without caching.
    """
    # LIST ALL TEMPLATES
   
    def list_templates(self) -> List[Dict[str, Any]]:
        """
        Return a summary list of all registered document templates.

        Each entry contains:
            - type_name: str (the enum value, e.g. "business_proposal")
            - description: str
            - section_count: int
            - required_fields: list[str]
            - optional_fields: list[str]

        Used by the GET /templates endpoint to let callers discover
        what document types the system supports.
        """
        summaries: List[Dict[str, Any]] = []

        for doc_type, template in DOCUMENT_TEMPLATES.items():
            summaries.append(self._template_to_summary(doc_type.value, template))

        return summaries

   
    # GET SINGLE TEMPLATE
  
    def get_template_detail(self, type_name: str) -> Optional[Dict[str, Any]]:
        """
        Return full metadata for a specific document template.

        Args:
            type_name: Document type string, e.g. "business_proposal".
                Case-insensitive; spaces and hyphens are normalized to
                underscores before lookup.

        Returns:
            Dict with all template metadata (including per-section
            guidance), or None if the type is not recognized.
        """
        normalized = type_name.strip().lower().replace(" ", "_").replace("-", "_")

        try:
            doc_type = DocumentType(normalized)
        except ValueError:
            logger.warning(
                "TemplateService: unknown document type '%s' (normalized: '%s')",
                type_name,
                normalized,
            )
            return None

        try:
            template = get_template(doc_type)
        except KeyError:
            return None

        detail = self._template_to_summary(doc_type.value, template)
        # Add per-section guidance for the detailed view.
        detail["sections"] = [
            {
                "name": section.name,
                "guidance": section.guidance,
                "order": idx + 1,
            }
            for idx, section in enumerate(template.sections)
        ]
        return detail

   
    # VALIDITY CHECK
    
    def is_valid_document_type(self, type_name: str) -> bool:
        """
        Check whether a type_name corresponds to a known document type.

        Used internally by agents and validation layers.
        Pure Python enum lookup.
        """
        normalized = type_name.strip().lower().replace(" ", "_").replace("-", "_")
        try:
            DocumentType(normalized)
            return True
        except ValueError:
            return False

    def get_all_type_names(self) -> List[str]:
        """
        Return the list of all registered document type name strings.

        Thin wrapper around templates.get_all_document_type_names() so
        callers can go through the service layer uniformly rather than
        importing from templates directly.
        """
        return get_all_document_type_names()

    # PRIVATE HELPERS
   
    @staticmethod
    def _template_to_summary(
        type_name: str, template: DocumentTemplate
    ) -> Dict[str, Any]:
        """
        Convert a DocumentTemplate into a JSON-serializable summary dict.

        Does NOT include per-section guidance (that's in get_template_detail).
        """
        return {
            "type_name": type_name,
            "description": template.description,
            "section_count": len(template.sections),
            "section_names": [s.name for s in template.sections],
            "required_fields": list(template.required_fields),
            "optional_fields": list(template.optional_fields),
        }
