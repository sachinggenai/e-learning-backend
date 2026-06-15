"""AI Template Contracts Router.

Exposes template contract definitions to the AI agent so it knows
exactly what data shapes are expected for each template type.

Endpoints:
    GET  /api/v1/ai/templates           — List all template contracts
    GET  /api/v1/ai/templates/{type_key} — Get single contract detail

TODOs by story:
    US-BKND-AI-007: Use contracts in session context window builder.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext
from app.services.ai.template_contracts import AITemplateContractsService
from app.services.ai.error_envelope import ai_error, AIErrorCode

router = APIRouter(prefix="/api/v1/ai", tags=["AI - Templates"])


@router.get("/templates")
async def list_template_contracts(
    include_legacy: bool = Query(False, description="Include deprecated/legacy contracts"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List all template contracts available to the AI agent.

    Returns the full list of registered template types with their
    JSON Schema definitions, business rules, and schema signatures.
    The AI session prompt builder consumes this at session start
    to embed the current contract set into the system prompt.

    FR-5: Template Registry Query API
    """
    svc = AITemplateContractsService(db)
    contracts = await svc.list_contracts(include_legacy=include_legacy)

    return {
        "version": "1.0.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "templates": contracts,
    }


@router.get("/templates/{type_key}")
async def get_template_contract_detail(
    type_key: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get a single template contract with its full JSON Schema.

    Returns the complete contract including the JSON Schema definition,
    business rules, and version/signature metadata.

    FR-5: Template Registry Query API (detail view)
    """
    svc = AITemplateContractsService(db)
    contract = await svc.get_contract(type_key)

    if contract is None:
        return ai_error(
            AIErrorCode.NOT_FOUND,
            f"Template type '{type_key}' not found. "
            f"Supported types: text-content, tabs, accordion, "
            f"click-reveal, final-assessment.",
        )

    # Enrich with the full JSON Schema for the detail view
    schema = await svc.get_schema_for_type(type_key)
    contract["json_schema"] = schema

    return contract
