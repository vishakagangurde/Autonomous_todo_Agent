"""
templates/document_templates.py

Pure-Python knowledge base of document structure.

Each template defines:
    description: short human-readable explanation of the document type.
    sections: ordered list of (section_name, guidance) — guidance is
        passed to the Content Generation Agent as generation context.
    required_fields: information the Planner's Missing Information
        Detector checks for; anything absent becomes a MissingField.
    optional_fields: nice-to-have information that improves output
        quality but does not trigger an Assumption if absent.
"""

from dataclasses import dataclass, field

from utils.constants import DocumentType


@dataclass(frozen=True)
class SectionDefinition:
    """A single section within a document template."""

    name: str
    guidance: str


@dataclass(frozen=True)
class DocumentTemplate:
    """
    Full structural definition of one document type.

    Frozen (immutable) because this is reference knowledge — nothing
    in the pipeline should ever mutate a template at runtime. Agents
    read from this; they never write to it.
    """

    description: str
    sections: tuple[SectionDefinition, ...]
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...] = field(default_factory=tuple)

    def section_names(self) -> list[str]:
        """Ordered list of section names only — convenience accessor."""
        return [s.name for s in self.sections]


DOCUMENT_TEMPLATES: dict[DocumentType, DocumentTemplate] = {
    DocumentType.BUSINESS_PROPOSAL: DocumentTemplate(
        description=(
            "A persuasive document proposing a business idea, product, "
            "or partnership to a prospective client, partner, or investor."
        ),
        sections=(
            SectionDefinition("Executive Summary", "High-level overview of the proposal and its core value proposition."),
            SectionDefinition("Problem Statement", "The specific problem or opportunity being addressed."),
            SectionDefinition("Proposed Solution", "Description of the product, service, or partnership being proposed."),
            SectionDefinition("Market Analysis", "Relevant market context, size, and competitive landscape."),
            SectionDefinition("Implementation Plan", "How the proposal would be executed, including timeline."),
            SectionDefinition("Pricing & Investment", "Cost structure, pricing, or investment terms."),
            SectionDefinition("Conclusion & Call to Action", "Summary and the specific next step requested from the reader."),
        ),
        required_fields=("topic", "audience"),
        optional_fields=("budget", "timeline", "company_name"),
    ),
    DocumentType.PROJECT_PLAN: DocumentTemplate(
        description=(
            "A structured plan describing how a project will be executed, "
            "including scope, timeline, resources, and risks."
        ),
        sections=(
            SectionDefinition("Project Overview", "Goal, scope, and background of the project."),
            SectionDefinition("Objectives & Success Criteria", "Measurable goals that define project success."),
            SectionDefinition("Scope & Deliverables", "What is included and explicitly excluded from the project."),
            SectionDefinition("Timeline & Milestones", "Key phases, milestones, and target dates."),
            SectionDefinition("Resource Allocation", "Team members, roles, and tools/budget required."),
            SectionDefinition("Risk Assessment", "Anticipated risks and mitigation strategies."),
            SectionDefinition("Conclusion", "Summary of the plan and expected outcome."),
        ),
        required_fields=("topic",),
        optional_fields=("timeline", "team_size", "budget"),
    ),
    DocumentType.MEETING_MINUTES: DocumentTemplate(
        description=(
            "A formal record of what was discussed and decided during a meeting."
        ),
        sections=(
            SectionDefinition("Meeting Details", "Date, time, location/platform, and attendees."),
            SectionDefinition("Agenda Overview", "Topics planned for discussion."),
            SectionDefinition("Discussion Summary", "Key points raised during the meeting, organized by topic."),
            SectionDefinition("Decisions Made", "Concrete decisions reached during the meeting."),
            SectionDefinition("Action Items", "Tasks assigned, owners, and due dates."),
            SectionDefinition("Next Steps", "What happens next, including the next meeting if applicable."),
        ),
        required_fields=("topic",),
        optional_fields=("attendees", "date"),
    ),
    DocumentType.BUSINESS_REPORT: DocumentTemplate(
        description=(
            "An analytical report presenting findings, performance data, "
            "or business analysis to stakeholders."
        ),
        sections=(
            SectionDefinition("Executive Summary", "Condensed overview of the report's key findings."),
            SectionDefinition("Introduction", "Purpose and scope of the report."),
            SectionDefinition("Methodology", "How the data or analysis was gathered, if applicable."),
            SectionDefinition("Findings & Analysis", "Core analytical content — the substance of the report."),
            SectionDefinition("Recommendations", "Actionable recommendations based on the findings."),
            SectionDefinition("Conclusion", "Summary of the report and its implications."),
        ),
        required_fields=("topic", "audience"),
        optional_fields=("data_period", "department"),
    ),
    DocumentType.TECHNICAL_DESIGN: DocumentTemplate(
        description=(
            "A technical document describing the architecture and design "
            "decisions behind a software system or feature."
        ),
        sections=(
            SectionDefinition("Overview", "What is being built and why, in plain terms."),
            SectionDefinition("Goals & Non-Goals", "Explicit scope boundaries for the design."),
            SectionDefinition("System Architecture", "High-level architecture and component interaction."),
            SectionDefinition("Detailed Design", "Deeper technical detail on key components or flows."),
            SectionDefinition("Alternatives Considered", "Other approaches considered and why they were rejected."),
            SectionDefinition("Risks & Tradeoffs", "Known limitations, risks, and engineering tradeoffs."),
            SectionDefinition("Rollout Plan", "How the design will be implemented and deployed safely."),
        ),
        required_fields=("topic",),
        optional_fields=("team_size", "timeline"),
    ),
    DocumentType.SOP: DocumentTemplate(
        description=(
            "A Standard Operating Procedure describing a repeatable "
            "process step-by-step for consistent execution."
        ),
        sections=(
            SectionDefinition("Purpose", "Why this procedure exists and what it governs."),
            SectionDefinition("Scope", "Who and what this procedure applies to."),
            SectionDefinition("Responsibilities", "Roles responsible for executing this procedure."),
            SectionDefinition("Procedure Steps", "The detailed, ordered steps of the procedure."),
            SectionDefinition("Exceptions & Edge Cases", "Situations that deviate from the standard flow."),
            SectionDefinition("Revision History", "Notes on how this procedure has changed over time."),
        ),
        required_fields=("topic",),
        optional_fields=("department", "owner"),
    ),
    DocumentType.PRODUCT_SPECIFICATION: DocumentTemplate(
        description=(
            "A specification describing what a product or feature should "
            "do, for engineering, design, or stakeholder alignment."
        ),
        sections=(
            SectionDefinition("Overview", "What the product/feature is and the problem it solves."),
            SectionDefinition("Target Users", "Who this product/feature is built for."),
            SectionDefinition("Requirements", "Functional and non-functional requirements."),
            SectionDefinition("User Flows", "Key user journeys through the product/feature."),
            SectionDefinition("Success Metrics", "How success will be measured post-launch."),
            SectionDefinition("Out of Scope", "What is explicitly not being built."),
        ),
        required_fields=("topic", "audience"),
        optional_fields=("timeline", "platform"),
    ),
    DocumentType.GENERIC_REPORT: DocumentTemplate(
        description=(
            "A general-purpose fallback report template used when the "
            "request doesn't clearly match a more specific document type."
        ),
        sections=(
            SectionDefinition("Introduction", "Purpose and context of the document."),
            SectionDefinition("Main Content", "Core body of the document, covering the requested topic."),
            SectionDefinition("Summary", "Concise wrap-up of the key points covered."),
        ),
        required_fields=("topic",),
        optional_fields=("audience",),
    ),
}


def get_template(document_type: DocumentType) -> DocumentTemplate:
    """
    Retrieve the template for a given document type.

    Pure Python dictionary lookup — this is the function
    agents/planner.py calls instead of ever asking Gemini for section
    structure. Raises a clear error if somehow called with a type not
    in the registry, rather than silently returning None.
    """
    template = DOCUMENT_TEMPLATES.get(document_type)
    if template is None:
        raise KeyError(
            f"No template registered for document type '{document_type}'. "
            f"Available types: {[t.value for t in DOCUMENT_TEMPLATES]}"
        )
    return template


def get_all_document_type_names() -> list[str]:
    """
    Return the list of valid document type name strings.

    This is the closed vocabulary Gemini is allowed to pick from during
    intent classification. Keeping it as a function (rather than a
    module-level constant) ensures it always reflects the current
    DOCUMENT_TEMPLATES registry without needing a separate sync step.
    """
    return [doc_type.value for doc_type in DOCUMENT_TEMPLATES]