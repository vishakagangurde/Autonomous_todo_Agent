"""
app.py

FastAPI application entry point for the Autonomous DOCX Agent.

Responsibilities:
    - Create and configure the FastAPI app instance.
    - Mount all HTTP route handlers.
    - Register global exception handlers.
    - Provide a startup lifespan hook for early validation.

Design rules:
    - This file contains NO business logic and NO Gemini calls.
    - All heavy work is delegated to the service layer
      (DocumentService, ExecutionService, TemplateService).
    - Each route is intentionally thin: validate → delegate → return.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from config import settings
from models.request import AgentRequest
from models.response import AgentResponse
from services.document_service import DocumentService
from services.execution_service import ExecutionService
from services.template_service import TemplateService

logger = logging.getLogger(__name__)

# Service singletons — instantiated once at startup, reused across requests

_document_service: DocumentService | None = None
_execution_service: ExecutionService | None = None
_template_service: TemplateService | None = None


def _get_document_service() -> DocumentService:
    global _document_service
    if _document_service is None:
        _document_service = DocumentService()
    return _document_service


def _get_execution_service() -> ExecutionService:
    global _execution_service
    if _execution_service is None:
        _execution_service = ExecutionService()
    return _execution_service


def _get_template_service() -> TemplateService:
    global _template_service
    if _template_service is None:
        _template_service = TemplateService()
    return _template_service

# Lifespan — startup / shutdown logic

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    On startup:
        - Confirms output directory exists (settings.ensure_output_dir_exists()
          is already called inside get_settings(), but we log it here for clarity).
        - Eagerly instantiates services so the first real request is fast.

    On shutdown:
        - Nothing to clean up (stateless services, no persistent connections).
    """
    logger.info("=== %s starting up ===", settings.app_name)
    logger.info("Model  : %s", settings.nvidia_model_name)
    logger.info("Output : %s", settings.output_dir.resolve())

    # Eagerly init services (validates orchestrator wiring at startup)
    _get_document_service()
    _get_execution_service()
    _get_template_service()

    logger.info("All services initialized — ready to accept requests.")
    yield
    logger.info("=== %s shutting down ===", settings.app_name)


# FastAPI app
app = FastAPI(
    title=settings.app_name,
    description=(
        "An autonomous multi-agent system that generates DOCX documents "
        "from a single natural-language request. "
        "The pipeline: Planner → Content Generator → Reviewer → Document Generator."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Global exception handlers

@app.exception_handler(ValidationError)
async def pydantic_validation_error_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    """
    Catch Pydantic validation errors that escape route-level handling.

    This should only fire for edge-cases outside the normal request flow
    (e.g., programmatic misuse). Route-level validation errors return 422
    automatically by FastAPI.
    """
    logger.warning("Unexpected ValidationError on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Last-resort handler for any unhandled exception.

    Logs the full traceback and returns a sanitized 500 so internal
    details are never leaked to the caller.
    """
    logger.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An unexpected internal error occurred. "
                      "Please check the server logs for details."
        },
    )






# ---- Health / Info ---------------------------------------------------------

@app.get(
    "/health",
    summary="Health check",
    tags=["System"],
    response_model=Dict[str, Any],
)
async def health_check() -> Dict[str, Any]:
    """
    Lightweight liveness probe.

    Returns HTTP 200 with a JSON body confirming the service is running
    and which Gemini model is configured. Does NOT make a live Gemini
    call — purely Python (fast, side-effect-free).
    """
    return {
        "status": "ok",
        "app": settings.app_name,
        **_get_document_service().get_pipeline_metadata(),
    }


@app.get(
    "/info",
    summary="Pipeline configuration",
    tags=["System"],
    response_model=Dict[str, Any],
)
async def pipeline_info() -> Dict[str, Any]:
    """
    Return full pipeline configuration metadata.

    Useful for debugging and for integration tests that need to
    know what model / limits are active without parsing config files.
    """
    meta = _get_document_service().get_pipeline_metadata()
    meta["supported_document_types"] = _get_template_service().get_all_type_names()
    return meta


# ---- Document Generation ---------------------------------------------------

@app.post(
    "/agent",
    summary="Generate a DOCX document",
    tags=["Agent"],
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_document(body: AgentRequest) -> AgentResponse:
    """
    Trigger the full autonomous document generation pipeline.

    **Request body**:
    ```json
    { "request": "Create a business proposal for a SaaS startup..." }
    ```

    **Pipeline stages**:
    1. **Planner** — analyses the request, infers document type, resolves
       missing fields with smart defaults/assumptions.
    2. **Content Generator** — writes each section using the plan + Gemini.
    3. **Reviewer** — evaluates quality; triggers selective regeneration
       if a section falls below threshold.
    4. **Document Generator** — assembles the reviewed sections into a
       `.docx` file and saves it to the configured output directory.

    **Returns** an `AgentResponse` containing the file path, a plan
    summary, and any assumptions the planner made autonomously.
    """
    logger.info("POST /agent — request_len=%d", len(body.request))
    response = _get_document_service().generate(body.request)
    return response


# ---- File Download ---------------------------------------------------------

@app.get(
    "/download/{filename}",
    summary="Download a generated DOCX file",
    tags=["Files"],
)
async def download_document(filename: str) -> FileResponse:
    """
    Download a previously generated `.docx` file by its filename.

    The filename is the basename returned in `AgentResponse.file_path`
    after a successful POST /agent call (e.g.
    `business_proposal_20260706_143012.docx`).

    Returns HTTP 404 if the file does not exist or has been purged.
    Raises HTTP 400 if the filename contains path-traversal sequences
    to prevent directory traversal attacks.
    """
    # Guard against path traversal (e.g. "../../etc/passwd")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    file_path: Path = settings.output_dir / filename

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File '{filename}' not found in the output directory.",
        )

    return FileResponse(
        path=str(file_path),
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        filename=filename,
    )


# ---- Execution Plans -------------------------------------------------------

@app.get(
    "/plans",
    summary="List all saved execution plans",
    tags=["Plans"],
    response_model=List[Dict[str, Any]],
)
async def list_plans() -> List[Dict[str, Any]]:
    """
    Return metadata for all execution plans saved to disk.

    Each entry contains the plan filename, the document type, and the
    timestamp when it was saved. Plans are ordered newest-first.

    This endpoint is useful for auditing what the system decided for
    each request — a key part of demonstrating autonomous behaviour.
    """
    return _get_execution_service().list_saved_plans()


@app.get(
    "/plans/{plan_filename}",
    summary="Get a specific execution plan",
    tags=["Plans"],
    response_model=Dict[str, Any],
)
async def get_plan(plan_filename: str) -> Dict[str, Any]:
    """
    Retrieve the full JSON content of a saved execution plan.

    Args:
        plan_filename: The basename of the plan JSON file
            (e.g. `plan_business_proposal_20260706_143012.json`).

    Returns HTTP 404 if the plan file does not exist.
    """
    if ".." in plan_filename or "/" in plan_filename or "\\" in plan_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid plan filename.",
        )

    plan = _get_execution_service().load_plan_summary(plan_filename)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{plan_filename}' not found.",
        )
    return plan


# ---- Templates -------------------------------------------------------------

@app.get(
    "/templates",
    summary="List all supported document templates",
    tags=["Templates"],
    response_model=List[Dict[str, Any]],
)
async def list_templates() -> List[Dict[str, Any]]:
    """
    Return a summary of all registered document templates.

    Each entry contains the document type name, description, section
    count, and lists of required/optional input fields. Useful for
    callers who want to craft a well-formed request upfront rather than
    relying on the Planner's assumptions.
    """
    return _get_template_service().list_templates()


@app.get(
    "/templates/{type_name}",
    summary="Get template detail for a specific document type",
    tags=["Templates"],
    response_model=Dict[str, Any],
)
async def get_template(type_name: str) -> Dict[str, Any]:
    """
    Return full metadata — including per-section writing guidance — for
    a specific document type.

    Args:
        type_name: Document type string (e.g. `business_proposal`,
            `project_plan`). Case-insensitive; spaces/hyphens are
            normalised to underscores.

    Returns HTTP 404 if the type is not registered.
    """
    detail = _get_template_service().get_template_detail(type_name)
    if detail is None:
        known = _get_template_service().get_all_type_names()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Document type '{type_name}' is not supported. "
                f"Known types: {known}"
            ),
        )
    return detail


# Dev entrypoint

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower(),
    )
