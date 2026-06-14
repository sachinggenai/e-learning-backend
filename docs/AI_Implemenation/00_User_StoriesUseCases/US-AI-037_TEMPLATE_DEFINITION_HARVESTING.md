# US-AI-037 — Template Definition Harvesting from AI Content (Full Epic)

---

## Section 1 — Title and Metadata

| Field | Value |
|---|---|
| **Epic ID** | US-AI-037 |
| **Title** | Template Definition Harvesting from AI Content |
| **Source Flow** | 25. Template Definition Harvesting |
| **Priority** | COULD for MVP, SHOULD for post-MVP library growth |
| **Depends On** | US-AI-011 (Create Page Proposal and Apply), US-AI-019 (Full Course from Uploaded File), US-AI-005 (Tool and Template Contract Registry) |
| **Unlocks** | Reusable template library growth (US-AI-030 Course Assembly), cross-course pattern discovery (US-AI-015 Similar Course Retrieval), training data pipeline (US-AI-031 RLHF Feedback) |
| **Status** | DRAFT |
| **Author** | Technical Product Owner |
| **Audit Reference** | RESEARCH_AUDIT.md — US-AI-037 rating: "Missing: Signature hashing algorithm. Similarity threshold. Admin review workflow. Promotion API contract." |
| **Backend Codebase** | FastAPI + SQLAlchemy async + PostgreSQL. Models in `app/models/persisted_course.py`, repos in `app/repositories/template_definition_repo.py` and `app/repositories/template_type_repo.py`, schema inference in `app/services/schema_inference.py`, renderer manifest in `app/services/renderer_manifest.py` |

---

## Section 2 — Business Context and User Story

### User Story (Standard)

> **As a Course Designer**, I want AI-generated pages with novel component structures to be harvestable as reusable template definitions, so that good AI outputs become available for manual authoring and future AI generation without requiring engineering involvement.

### Enriched Context

The platform already supports 84 template types defined in `app/services/renderer_manifest.py`, with their renderer capabilities expressed in `app/models/export_contract.py`. The `TemplateDefinition` ORM model (`app/models/persisted_course.py`, lines 112-145) and `TemplateType` model (`app/models/template_type.py`, lines 16-87) store template schemas and type metadata respectively. The `TemplateDefinitionRepository` (`app/repositories/template_definition_repo.py`) provides `get_by_type_key`, `get_by_schema_signature`, `create`, and `list_all` methods.

The existing `SchemaInferenceEngine` (`app/services/schema_inference.py`) already computes deterministic SHA-256 schema signatures and infers field schemas from data. The `ImportService._harvest_templates` method (`app/services/import_service.py`, lines 506-583) performs a basic harvest during SCORM imports — it promotes templates to `template_types` using schema signatures for deduplication — but it operates on the `TemplateType` table (the "template picker UI" model), not the `TemplateDefinition` table (the "rendering engine" model).

This gap means:
1. **AI-generated pages with novel structures do not automatically become template definitions.** An admin must manually copy/paste schemas.
2. **The harvest pipeline from AI content is separate from the SCORM import harvest.** The `ImportService._harvest_templates` path is only called during `commit_import`, not during AI proposal apply.
3. **There is no similarity detection.** If an AI-generated page is 90% similar to an existing definition, it is stored as a duplicate rather than flagged as a variant.
4. **There is no admin review workflow.** Harvested templates go directly into the database without quality review or provenance tracking.

This epic builds a dedicated `TemplateHarvester` service (`app/services/ai/template_harvester.py`) that:
- Runs idempotently after every AI page creation or course generation
- Computes canonical field schemas using the existing `SchemaInferenceEngine`
- Matches against existing `TemplateDefinition` records via `schema_signature`
- Flags near-matches (similarity >70% but not exact) for admin review
- Creates `TemplateDefinition` records for truly novel schemas
- Records provenance linking back to the AI session, proposal, and course
- Emits an outbox event (`TemplateDefinitionHarvested`) for downstream consumers

### Business Impact

| Metric | Without Harvesting | With Harvesting | Source |
|---|---|---|---|
| Template library growth rate | Manual only (engineer hours) | Automatic + admin approval | Operations data |
| Time to make AI pattern available | Days (manual schema authoring) | Minutes (admin review + publish) | Engineering estimate |
| Duplicate template definitions | Common (no dedupe between courses) | Eliminated by schema signature | Code analysis |
| Near-match discovery | Impossible | Flagged for admin review | Feature design |
| Provenance tracking | None | Full trace to session/proposal | Audit requirements |

---

## Section 3 — Functional Requirements

### FR-1: Automatic Harvest on AI Page Creation

When an AI page is successfully applied (via `apply_page_proposal` from US-AI-011 or `apply_batch_proposals` from US-AI-029), the system MUST asynchronously invoke the template harvester with the applied page data. The harvester MUST:

1. Extract the page's component data structure
2. Flatten multi-component pages into individual component schemas
3. Compute the canonical field schema for each component using `SchemaInferenceEngine.infer_schema_from_data`
4. Compute the schema signature using `SchemaInferenceEngine.compute_schema_signature`
5. Match against existing `TemplateDefinition` records by `schema_signature`
6. Classify the result as: `EXACT_MATCH`, `NEAR_MATCH`, or `NOVEL`

**Harvest classification rules:**

| Classification | Condition | Action |
|---|---|---|
| `EXACT_MATCH` | Schema signature matches an existing active `TemplateDefinition` | No-op; increment usage count |
| `NEAR_MATCH` | No exact match, but signature similarity >0.70 (field overlap ratio) | Create pending `TemplateDefinition` draft; flag for admin review |
| `NOVEL` | No match and no near-match found | Create pending `TemplateDefinition` draft; flag for admin review |

### FR-2: Similarity Scoring for Near-Match Detection

The harvester MUST compute a similarity score between candidate and existing schemas using the following algorithm:

```
similarity(A, B) = (2 * |fields_A ∩ fields_B|) / (|fields_A| + |fields_B|)
```

Where field equality requires:
- Same `name` (case-insensitive)
- Same `type` (after type mapping normalization)
- Same `required` flag

A score of `1.0` is an exact match (and would have been caught by signature matching). A score of `>0.70` is a near-match. The threshold is configurable via env var `AI_HARVEST_SIMILARITY_THRESHOLD` (default `0.70`).

The NEAR_MATCH response MUST include:
- The matched `TemplateDefinition.type_key` and `display_name`
- The similarity score
- A field-level diff showing: added fields, removed fields, type-changed fields

### FR-3: Harvest Execution Modes

The harvester supports two execution modes:

| Mode | Trigger | Behavior |
|---|---|---|
| `synchronous` | During proposal apply (inline) | Runs harvest in the same request; adds harvest results to apply response. Non-blocking: harvest failure does not roll back the page creation. |
| `asynchronous` | Via outbox event consumer | Runs harvest as a background job. Used for batch course generation and post-hoc harvesting. Emits `TemplateDefinitionHarvested` outbox event. |

The mode is controlled by `AI_HARVEST_MODE` env var (default `synchronous`).

### FR-4: Admin Review and Promotion Workflow

Every harvested template definition starts with `is_active=False` (DRAFT status). An admin or course designer can:

1. **Preview:** View the harvested template's field schema, render template HTML, and a sample data payload from the originating page
2. **Edit:** Modify the `display_name`, `field_schema`, `render_config`, `scorm_behavior`, and `html_template` before publishing
3. **Publish:** Set `is_active=True`, making it available in the template picker and AI tool allowlist
4. **Reject:** Delete or soft-delete the draft with an optional reason
5. **Merge:** For near-matches, merge the candidate fields into the existing template definition

The review queue is accessible via `GET /api/v1/ai/harvest/pending` (admin-only).

### FR-5: Provenance Tracking

Every harvested `TemplateDefinition` MUST record its provenance in the `schema_json` field:

```json
{
  "harvest": {
    "source_session_id": "uuid-of-ai-session",
    "source_proposal_id": "uuid-of-proposal",
    "source_course_id": "course-abc",
    "source_page_id": "page-123",
    "source_component_type": "accordion",
    "harvested_at": "2026-06-14T12:00:00Z",
    "harvest_strategy": "synchronous",
    "model_id": "claude-sonnet-4-20250514",
    "pipeline_version": "1.0"
  },
  "field_schema": [ ... ],
  "render_config": { ... },
  "sanitize_rules": { ... },
  "scorm_behavior": { ... },
  "renderer_class": "app.services.scorm.renderers.dynamic.DynamicTemplateRenderer",
  "layout_version": 1
}
```

### FR-6: Outbox Event Emission

On successful harvest (any classification), the harvester MUST write an outbox event (ref. US-AI-033). Event type: `TemplateDefinitionHarvested`, version `1.0`.

**Outbox event payload:**

```json
{
  "event_type": "TemplateDefinitionHarvested",
  "event_version": "1.0",
  "aggregate_id": "<template_type_key>",
  "payload": {
    "classification": "NOVEL",
    "template_type_key": "ai-accordion-v2",
    "schema_signature": "abc123...",
    "display_name": "AI Accordion v2",
    "source_session_id": "uuid",
    "source_proposal_id": "uuid",
    "source_course_id": "course-abc",
    "is_active": false,
    "similarity_score": null
  },
  "occurred_at": "2026-06-14T12:00:00Z"
}
```

### FR-7: Harvest Report in Proposal Apply Response

When harvest mode is `synchronous`, the proposal apply response MUST include a `harvest` field:

```json
{
  "status": "applied",
  "proposal_id": "uuid",
  "page_id": "page-123",
  "harvest": {
    "harvested": 2,
    "exact_matches": 1,
    "near_matches": 0,
    "novel": 1,
    "results": [
      {
        "component_type": "content-text",
        "classification": "EXACT_MATCH",
        "matched_type_key": "content-text",
        "confidence": 1.0
      },
      {
        "component_type": "custom-accordion",
        "classification": "NOVEL",
        "draft_type_key": "harvested_<signature_prefix>",
        "confidence": 1.0,
        "is_active": false
      }
    ]
  }
}
```

---

## Section 4 — Technical Design and API Contracts

### 4.1 New File: `app/services/ai/template_harvester.py`

```python
"""
Template Definition Harvester for AI-Generated Content.

Harvests reusable template definitions from AI-created page data.
Integrates with SchemaInferenceEngine for schema detection and
TemplateDefinitionRepository for persistence.
"""
import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persisted_course import TemplateDefinition
from app.models.template_schema import (
    FieldSchema,
    RenderConfig,
    ScormBehavior,
    TemplateDefinition as TemplateDefinitionPydantic,
)
from app.repositories.template_definition_repo import (
    TemplateDefinitionRepository,
    TemplateDefinitionNotFoundError,
)
from app.repositories.template_type_repo import TemplateTypeRepository
from app.services.renderer_manifest import get_renderer_manifest
from app.services.schema_inference import SchemaInferenceEngine

logger = logging.getLogger(__name__)

# ── Enums and Constants ──────────────────────────────────────────────────────

class HarvestClassification(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    NEAR_MATCH = "NEAR_MATCH"
    NOVEL = "NOVEL"

HARVEST_PIPELINE_VERSION = "1.0"

# ── Data Contracts ───────────────────────────────────────────────────────────

@dataclass
class HarvestResult:
    """Result of harvesting a single component."""
    component_type: str
    classification: HarvestClassification
    schema_signature: str
    matched_type_key: Optional[str] = None
    matched_display_name: Optional[str] = None
    similarity_score: Optional[float] = None
    draft_type_key: Optional[str] = None
    created_definition_id: Optional[int] = None
    is_active: bool = False
    error: Optional[str] = None

@dataclass
class HarvestReport:
    """Aggregated harvest report for a proposal apply."""
    harvested: int = 0
    exact_matches: int = 0
    near_matches: int = 0
    novel: int = 0
    results: List[HarvestResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

# ── Similarity Engine ────────────────────────────────────────────────────────

class SchemaSimilarityEngine:
    """Computes similarity between field schemas for near-match detection."""

    @staticmethod
    def compute_similarity(
        candidate_fields: List[Dict[str, Any]],
        existing_fields: List[Dict[str, Any]],
    ) -> float:
        """
        Compute Jaccard-like similarity between two field schemas.

        Returns 1.0 for identical field sets, 0.0 for completely disjoint.
        Threshold for near-match is defined in env AI_HARVEST_SIMILARITY_THRESHOLD.
        """
        if not candidate_fields and not existing_fields:
            return 1.0
        if not candidate_fields or not existing_fields:
            return 0.0

        def _field_key(f: Dict[str, Any]) -> Tuple[str, str, bool]:
            return (
                str(f.get("name", "")).lower(),
                str(f.get("type", "text")),
                bool(f.get("required", True)),
            )

        candidate_keys = {_field_key(f) for f in candidate_fields if isinstance(f, dict)}
        existing_keys = {_field_key(f) for f in existing_fields if isinstance(f, dict)}

        if not candidate_keys and not existing_keys:
            return 1.0

        intersection = candidate_keys & existing_keys
        union = candidate_keys | existing_keys

        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def field_diff(
        candidate_fields: List[Dict[str, Any]],
        existing_fields: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Compute field-level diff between candidate and existing schemas."""
        def _field_key(f: Dict[str, Any]) -> str:
            return str(f.get("name", "")).lower()

        existing_map = {_field_key(f): f for f in existing_fields if isinstance(f, dict)}
        candidate_map = {_field_key(f): f for f in candidate_fields if isinstance(f, dict)}

        added = [candidate_map[k] for k in candidate_map if k not in existing_map]
        removed = [existing_map[k] for k in existing_map if k not in candidate_map]

        changed = []
        for name in candidate_map:
            if name in existing_map:
                c = candidate_map[name]
                e = existing_map[name]
                if c.get("type") != e.get("type") or c.get("required") != e.get("required"):
                    changed.append({"name": name, "from": e, "to": c})

        return {"added": added, "removed": removed, "changed": changed}

# ── Main Harvester Service ───────────────────────────────────────────────────

class TemplateHarvester:
    """
    Harvests template definitions from AI-generated page data.

    Usage:
        harvester = TemplateHarvester(db_session)
        report = await harvester.harvest_from_page(
            page_data={"components": [...]},
            source_session_id="uuid",
            source_proposal_id="uuid",
            source_course_id="course-abc",
            source_page_id="page-123",
            model_id="claude-sonnet-4-20250514",
        )
    """

    def __init__(
        self,
        session: AsyncSession,
        similarity_threshold: float = 0.70,
        harvest_mode: str = "synchronous",
    ):
        self.session = session
        self.definition_repo = TemplateDefinitionRepository(session)
        self.template_type_repo = TemplateTypeRepository(session)
        self.schema_engine = SchemaInferenceEngine()
        self.similarity_engine = SchemaSimilarityEngine()
        self.similarity_threshold = similarity_threshold
        self.harvest_mode = harvest_mode
        self.manifest = get_renderer_manifest()

    async def harvest_from_page(
        self,
        page_data: Dict[str, Any],
        source_session_id: str,
        source_proposal_id: str,
        source_course_id: str,
        source_page_id: str,
        model_id: str = "unknown",
    ) -> HarvestReport:
        """
        Harvest template definitions from an AI-created page.

        Args:
            page_data: The full page data dict (may contain 'components' list)
            source_session_id: AI session that created this page
            source_proposal_id: Proposal that was applied
            source_course_id: Course containing the page
            source_page_id: The created page ID
            model_id: LLM model that generated the content

        Returns:
            HarvestReport with per-component results
        """
        report = HarvestReport()
        components = page_data.get("components", [page_data])

        for component in components:
            if not isinstance(component, dict):
                report.errors.append("Invalid component data: not a dict")
                continue

            result = await self._harvest_component(
                component=component,
                source_session_id=source_session_id,
                source_proposal_id=source_proposal_id,
                source_course_id=source_course_id,
                source_page_id=source_page_id,
                model_id=model_id,
            )
            report.results.append(result)
            if result.error:
                report.errors.append(f"{result.component_type}: {result.error}")
            elif result.classification == HarvestClassification.EXACT_MATCH:
                report.exact_matches += 1
            elif result.classification == HarvestClassification.NEAR_MATCH:
                report.near_matches += 1
            elif result.classification == HarvestClassification.NOVEL:
                report.novel += 1

        report.harvested = len(report.results)
        return report

    async def _harvest_component(
        self,
        component: Dict[str, Any],
        source_session_id: str,
        source_proposal_id: str,
        source_course_id: str,
        source_page_id: str,
        model_id: str,
    ) -> HarvestResult:
        """Harvest a single component."""
        component_type = component.get("componentType") or component.get("type", "unknown")
        component_data = component.get("data", component)

        result = HarvestResult(component_type=component_type, schema_signature="")

        # Step 1: Infer schema from component data
        if isinstance(component_data, dict):
            try:
                schema = self.schema_engine.infer_schema_from_data(component_data)
            except Exception as e:
                result.error = f"Schema inference failed: {e}"
                return result
        else:
            result.error = "Component data is not a dict; skipping"
            return result

        # Step 2: Compute schema signature
        try:
            schema_signature = self.schema_engine.compute_schema_signature(schema)
        except Exception as e:
            result.error = f"Signature computation failed: {e}"
            return result
        result.schema_signature = schema_signature

        # Step 3: Check for exact match by signature
        try:
            existing = await self.definition_repo.get_by_schema_signature(schema_signature)
            if existing:
                result.classification = HarvestClassification.EXACT_MATCH
                result.matched_type_key = existing.type_key
                result.matched_display_name = existing.type_key.replace("-", " ").title()
                result.similarity_score = 1.0
                await self._increment_usage(existing)
                return result
        except Exception as e:
            logger.debug(f"Error checking exact match: {e}")

        # Step 4: Check for near-matches against existing definitions
        try:
            all_definitions = await self.definition_repo.list_all()
        except Exception as e:
            logger.debug(f"Error listing definitions for near-match: {e}")
            all_definitions = []

        best_match: Optional[TemplateDefinitionPydantic] = None
        best_score = 0.0

        candidate_fields = schema.get("fields", [])
        for definition in all_definitions:
            existing_fields = [
                f.model_dump() if hasattr(f, "model_dump") else dict(f)
                for f in definition.field_schema
            ]
            score = self.similarity_engine.compute_similarity(
                candidate_fields, existing_fields
            )
            if score > best_score:
                best_score = score
                best_match = definition

        if best_match and best_score >= self.similarity_threshold:
            result.classification = HarvestClassification.NEAR_MATCH
            result.matched_type_key = best_match.type_key
            result.matched_display_name = best_match.display_name
            result.similarity_score = best_score
        else:
            result.classification = HarvestClassification.NOVEL
            result.similarity_score = best_score if best_match else 0.0

        # Step 5: Create draft TemplateDefinition for novel/near-match
        if result.classification in (HarvestClassification.NOVEL, HarvestClassification.NEAR_MATCH):
            try:
                template_def = self._build_template_definition(
                    component_type=component_type,
                    schema=schema,
                    schema_signature=schema_signature,
                    source_session_id=source_session_id,
                    source_proposal_id=source_proposal_id,
                    source_course_id=source_course_id,
                    source_page_id=source_page_id,
                    model_id=model_id,
                    component_data=component_data,
                    near_match_base=result.matched_type_key,
                )
                created = await self.definition_repo.create(template_def)
                result.draft_type_key = created.type_key
                result.created_definition_id = id(created)  # placeholder; repo returns Pydantic
                result.is_active = False

                # Refresh to get actual ID
                fresh = await self.definition_repo.get_by_type_key(created.type_key)
                result.created_definition_id = getattr(fresh, "id", None)

            except Exception as e:
                result.error = f"Failed to create draft definition: {e}"

        return result

    def _build_template_definition(
        self,
        component_type: str,
        schema: Dict[str, Any],
        schema_signature: str,
        source_session_id: str,
        source_proposal_id: str,
        source_course_id: str,
        source_page_id: str,
        model_id: str,
        component_data: Dict[str, Any],
        near_match_base: Optional[str] = None,
    ) -> TemplateDefinitionPydantic:
        """Build a TemplateDefinitionPydantic from harvested data."""
        fields = schema.get("fields", [])
        field_schema_list = []
        for f in fields:
            raw_type = str(f.get("type", "text"))
            type_map = {
                "integer": "number", "array": "list", "array[object]": "list",
                "url": "text", "null": "text", "unknown": "text",
            }
            field_type = type_map.get(raw_type, raw_type)
            if field_type not in {"text", "html", "boolean", "number", "list", "object"}:
                field_type = "text"
            sanitize_strategy = "html" if field_type == "html" else "text"
            field_schema_list.append(FieldSchema(
                name=str(f.get("name", "field")),
                type=field_type,
                sanitize_strategy=sanitize_strategy,
                required=bool(f.get("required", True)),
            ))

        # Determine type_key
        base_type = near_match_base or component_type
        signature_prefix = schema_signature[:8]
        type_key = f"harvested_{base_type}_{signature_prefix}"

        # Determine render config based on component type and fields
        component_type_lower = component_type.lower()
        has_html = any(fs.type == "html" for fs in field_schema_list)
        if "mcq" in component_type_lower or "quiz" in component_type_lower:
            render_component_type = "mcq"
        elif "video" in component_type_lower:
            render_component_type = "video"
        elif has_html:
            render_component_type = "html"
        else:
            render_component_type = "html"

        render_config = RenderConfig(
            component_type=render_component_type,
            html_template=self.schema_engine.generate_render_template(schema, type_key),
            nested_fields=None,
            validation_rules=None,
        )

        # SCORM behavior inference
        if render_component_type == "mcq":
            scorm_behavior = ScormBehavior(
                interaction_type="choice",
                reports_score=True,
                objective_per_question=False,
                completion_threshold=None,
            )
        else:
            scorm_behavior = ScormBehavior(
                interaction_type="none",
                reports_score=False,
            )

        sanitize_rules = {
            fs.name: fs.sanitize_strategy for fs in field_schema_list
        }

        return TemplateDefinitionPydantic(
            type_key=type_key,
            schema_signature=schema_signature,
            field_schema=field_schema_list,
            render_config=render_config,
            sanitize_rules=sanitize_rules,
            scorm_behavior=scorm_behavior,
            renderer_class="app.services.scorm.renderers.dynamic.DynamicTemplateRenderer",
            layout_version=1,
        )

    async def _increment_usage(self, definition: TemplateDefinitionPydantic) -> None:
        """Increment usage count on the matching template type (best-effort)."""
        try:
            await self.template_type_repo.increment_usage(
                await self._resolve_type_id(definition.type_key)
            )
        except Exception as e:
            logger.debug(f"Failed to increment usage: {e}")

    async def _resolve_type_id(self, type_key: str) -> int:
        """Resolve a TemplateDefinition type_key to the TemplateType table id."""
        from sqlalchemy import select
        from app.models.template_type import TemplateType
        result = await self.session.execute(
            select(TemplateType.id).where(TemplateType.template_id == type_key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise TemplateDefinitionNotFoundError(f"Template type not found: {type_key}")
        return row
```

### 4.2 Integration Point: `app/repositories/template_definition_repo.py` — New Method

Add a `get_by_schema_signature_list` method for batch near-match checking:

```python
async def get_by_schema_signature_list(
    self, signatures: List[str]
) -> Dict[str, TemplateDefinition]:
    """Lookup multiple definitions by schema signature. Returns dict of signature->definition."""
    from sqlalchemy import select
    from app.models.persisted_course import TemplateDefinition as TemplateDefinitionRecord

    result = await self.session.execute(
        select(TemplateDefinitionRecord).where(
            TemplateDefinitionRecord.schema_signature.in_(signatures)
        )
    )
    records = result.scalars().all()
    return {r.schema_signature: self._to_definition(r) for r in records}
```

### 4.3 Integration Point: Proposal Apply Service — Harvest Hook

In the proposal apply flow (in `app/services/ai/proposal_service.py` or equivalent), after successful page creation:

```python
# After page persistence succeeds
if os.getenv("AI_HARVEST_ENABLED", "true").lower() == "true":
    harvester = TemplateHarvester(
        session=db_session,
        harvest_mode=os.getenv("AI_HARVEST_MODE", "synchronous"),
        similarity_threshold=float(os.getenv("AI_HARVEST_SIMILARITY_THRESHOLD", "0.70")),
    )
    harvest_report = await harvester.harvest_from_page(
        page_data=applied_page_data,
        source_session_id=session_id,
        source_proposal_id=proposal_id,
        source_course_id=course_id,
        source_page_id=created_page_id,
        model_id=model_used,
    )
    # Append harvest_report to the apply response
```

### 4.4 New API Endpoints

#### `GET /api/v1/ai/harvest/pending` — Admin Review Queue

List all harvested template definitions pending review (`is_active=False`).

**Request:**
```
GET /api/v1/ai/harvest/pending?page=1&per_page=20&classification=NOVEL
Authorization: Session <session_id>
```

**Response 200:**
```json
{
  "items": [
    {
      "id": 42,
      "templateType": "harvested_accordion_a1b2c3d4",
      "displayName": "Harvested Accordion A1b2c3d4",
      "classification": "NOVEL",
      "similarityScore": null,
      "matchedTypeKey": null,
      "fieldSchema": [
        {"name": "panels", "type": "list", "required": true}
      ],
      "renderTemplateHtml": "<div>...</div>",
      "provenance": {
        "sourceSessionId": "uuid",
        "sourceProposalId": "uuid",
        "sourceCourseId": "course-abc",
        "sourcePageId": "page-123",
        "harvestedAt": "2026-06-14T12:00:00Z",
        "modelId": "claude-sonnet-4-20250514"
      },
      "sampleData": {
        "panels": [
          {"title": "...", "content": "..."}
        ]
      },
      "createdAt": "2026-06-14T12:00:00Z"
    }
  ],
  "total": 5,
  "page": 1,
  "perPage": 20
}
```

#### `GET /api/v1/ai/harvest/{definition_id}` — Single Harvest Detail

**Request:**
```
GET /api/v1/ai/harvest/42
Authorization: Session <session_id>
```

**Response 200:** Same shape as a single item from the pending list.

#### `PATCH /api/v1/ai/harvest/{definition_id}/publish` — Publish to Template Library

**Request:**
```json
{
  "displayName": "AI Accordion v2",
  "renderTemplateHtml": "<div class='accordion'>...</div>",
  "finalizeSchema": true
}
```

**Response 200:**
```json
{
  "id": 42,
  "templateType": "harvested_accordion_a1b2c3d4",
  "displayName": "AI Accordion v2",
  "isActive": true,
  "publishedAt": "2026-06-14T12:30:00Z"
}
```

**Side effects:**
1. Sets `is_active=True` on the `TemplateDefinition` record
2. Creates or updates a corresponding `TemplateType` record so it appears in the template picker
3. Optionally seeds the renderer registry via `TemplateRegistry.load_definitions`
4. Emits a `TemplateDefinitionPublished` outbox event

#### `DELETE /api/v1/ai/harvest/{definition_id}` — Reject a Draft

**Response 204:** No content. Soft-deletes or hard-deletes depending on config.

#### `POST /api/v1/ai/harvest/{definition_id}/merge` — Merge into Existing

**Request:**
```json
{
  "targetTypeKey": "accordion",
  "mergeStrategy": "add_fields"
}
```

**Response 200:**
```json
{
  "sourceId": 42,
  "targetTypeKey": "accordion",
  "mergedFields": "panels",
  "result": "merged"
}
```

**Merge strategies:**

| Strategy | Behavior |
|---|---|
| `add_fields` | Add candidate's new fields to existing template as optional fields |
| `replace_schema` | Replace existing template's field schema with candidate's |
| `create_variant` | Create a new template type with a version suffix (e.g., `accordion-v2`) |

### 4.5 Database Schema

#### New Column on `TemplateDefinition` (`app/models/persisted_course.py`)

Add a `provenance_json` column to the existing `TemplateDefinition` model (lines 112-145):

```python
class TemplateDefinition(Base):
    # ... existing columns ...

    # Harvest provenance (for AI-harvested definitions)
    provenance_json: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, default=dict
    )
    # Classification at harvest time: EXACT_MATCH, NEAR_MATCH, NOVEL
    harvest_classification: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )
    # Template type this was matched against (for near-matches)
    harvest_matched_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    # Similarity score for near-matches
    harvest_similarity: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    # Admin review status: pending_review, published, rejected
    review_status: Mapped[str] = mapped_column(
        String(32), default="pending_review"
    )
```

#### Alembic Migration: `alembic/versions/YYYYMMDD_HHMM_add_harvest_columns.py`

```python
"""Add harvest columns to template_definitions

Revision ID: abc123def456
Revises: <parent_revision>
Create Date: 2026-06-14 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "abc123def456"
down_revision = "<parent_revision>"

def upgrade() -> None:
    op.add_column(
        "template_definitions",
        sa.Column("provenance_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "template_definitions",
        sa.Column("harvest_classification", sa.String(32), nullable=True),
    )
    op.add_column(
        "template_definitions",
        sa.Column("harvest_matched_type", sa.String(100), nullable=True),
    )
    op.add_column(
        "template_definitions",
        sa.Column("harvest_similarity", sa.Float(), nullable=True),
    )
    op.add_column(
        "template_definitions",
        sa.Column("review_status", sa.String(32),
                  nullable=False, server_default="pending_review"),
    )
    op.create_index(
        "ix_template_definitions_review_status",
        "template_definitions", ["review_status"],
    )
    op.create_index(
        "ix_template_definitions_harvest_classification",
        "template_definitions", ["harvest_classification"],
    )

def downgrade() -> None:
    op.drop_column("template_definitions", "provenance_json")
    op.drop_column("template_definitions", "harvest_classification")
    op.drop_column("template_definitions", "harvest_matched_type")
    op.drop_column("template_definitions", "harvest_similarity")
    op.drop_column("template_definitions", "review_status")
```

### 4.6 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AI_HARVEST_ENABLED` | `true` | Master switch for harvest pipeline |
| `AI_HARVEST_MODE` | `synchronous` | Execution mode: `synchronous` or `asynchronous` |
| `AI_HARVEST_SIMILARITY_THRESHOLD` | `0.70` | Near-match threshold (0.0 to 1.0) |
| `AI_HARVEST_MAX_PER_APPLY` | `10` | Max templates to harvest per apply (anti-pollution) |
| `AI_HARVEST_REVIEW_REQUIRED` | `true` | Require admin review before templates become active |
| `AI_HARVEST_DRAFT_TTL_DAYS` | `90` | Auto-delete unreviewed drafts after N days |

---

## Section 5 — Test Scenarios

### 5.1 Unit Tests (`tests/test_template_harvester.py`)

| Test ID | Scenario | Input | Expected Result |
|---|---|---|---|
| TH-001 | Exact match harvest | Component data matching existing `content-text` schema | `HarvestClassification.EXACT_MATCH`, `similarity_score=1.0`, no new record created |
| TH-002 | Novel schema harvest | Component with 3 new fields (title, body, footer) unknown to any definition | `HarvestClassification.NOVEL`, new `TemplateDefinition` created with `is_active=False`, type_key prefixed `harvested_` |
| TH-003 | Near-match detection | Component with 4 fields, 3 match existing, 1 is new | `HarvestClassification.NEAR_MATCH`, `similarity_score=0.857`, `matched_type_key` set to closest match |
| TH-004 | Empty component data | Component with empty dict | Error: "Component data is not a dict; skipping" |
| TH-005 | Non-dict component data | Component data is a string "hello" | Error: "Schema inference failed" |
| TH-006 | Multi-component page | Page with 3 components: 1 exact match, 1 near-match, 1 novel | Report: `exact_matches=1, near_matches=1, novel=1, harvested=3` |
| TH-007 | Duplicate prevention | Same novel schema harvested twice | First: NOVEL. Second: EXACT_MATCH (signature now exists) |
| TH-008 | Similarity threshold boundary | Similarity = 0.70 (exactly at threshold) | Classified as NEAR_MATCH |
| TH-009 | Similarity below threshold | Similarity = 0.50 (below threshold) | Classified as NOVEL |
| TH-010 | Component with list/array fields | Component data `{"items": [{"a": 1}, {"b": 2}]}` | Field type inferred as `"list"`, schema generated correctly |
| TH-011 | Component with HTML content | Component data `{"body": "<p>Hello</p>"}` | Field type `"html"`, `sanitize_strategy = "html"` |
| TH-012 | Component with nested object | Component data `{"config": {"enabled": true, "count": 5}}` | Field type `"object"`, nested_schema contains sub-fields |
| TH-013 | SchemaSimilarityEngine identical fields | Two identical field lists | similarity = 1.0 |
| TH-014 | SchemaSimilarityEngine disjoint fields | Two completely different field lists | similarity = 0.0 |
| TH-015 | SchemaSimilarityEngine empty candidate | Empty candidate fields list | similarity = 0.0 |
| TH-016 | SchemaSimilarityEngine both empty | Both field lists empty | similarity = 1.0 |
| TH-017 | Field diff computation | A -> B with 1 added, 1 removed, 1 changed field | Diff correctly identifies added/removed/changed |
| TH-018 | MCQLike component harvest | Component type "quiz-mcq" with questions data | `render_config.component_type = "mcq"`, `scorm_behavior.interaction_type = "choice"` |

### 5.2 API Integration Tests (`tests/test_harvest_api.py`)

| Test ID | Scenario | Endpoint | Expected Status |
|---|---|---|---|
| API-TH-001 | List pending harvests (admin) | `GET /api/v1/ai/harvest/pending` | 200, returns paginated list |
| API-TH-002 | List pending harvests (non-admin) | `GET /api/v1/ai/harvest/pending` (unauthorized) | 403 |
| API-TH-003 | Get single harvest detail | `GET /api/v1/ai/harvest/42` | 200, includes provenance and sample data |
| API-TH-004 | Get non-existent harvest | `GET /api/v1/ai/harvest/9999` | 404 |
| API-TH-005 | Publish harvested template | `PATCH /api/v1/ai/harvest/42/publish` | 200, `is_active=true` |
| API-TH-006 | Publish non-existent template | `PATCH /api/v1/ai/harvest/9999/publish` | 404 |
| API-TH-007 | Publish already-active template | `PATCH /api/v1/ai/harvest/42/publish` (already active) | 409 or 200 (idempotent) |
| API-TH-008 | Reject harvest draft | `DELETE /api/v1/ai/harvest/42` | 204 |
| API-TH-009 | Merge near-match into existing | `POST /api/v1/ai/harvest/42/merge` | 200 |
| API-TH-010 | Merge with invalid strategy | `POST /api/v1/ai/harvest/42/merge` (bad strategy) | 422 |
| API-TH-011 | Harvest included in proposal apply response | `POST /api/v1/ai/proposals/{id}/apply` | 200, response includes `harvest` field |
| API-TH-012 | Harvest disabled via env var | `AI_HARVEST_ENABLED=false` | No harvest in apply response |

### 5.3 Edge Cases

| Test ID | Scenario | Expected Behavior |
|---|---|---|
| EDGE-001 | Harvest fails (DB error) during apply | Apply succeeds; harvest error is logged but not propagated |
| EDGE-002 | 1000 templates pending review | Paginated list returns correct pages; no OOM |
| EDGE-003 | Near-match to a deleted/inactive template | Still match; do not skip inactive definitions |
| EDGE-004 | Component type is in renderer manifest as non-exportable | Still harvest; non-exportable components can become templates |
| EDGE-005 | Provenance JSON exceeds column size | Truncate or store reference instead of full payload |
| EDGE-006 | Two concurrent harvests of same novel schema | First creates draft; second detects exact match via signature |
| EDGE-007 | Admin publishes draft, then deletes it | Published state is lost; no dangling references |
| EDGE-008 | Schema has 50+ fields | Harvest succeeds; no field count limit hardcoded |

---

## Section 6 — Acceptance Criteria

| # | Criterion | Verification |
|---|---|---|
| AC-1 | AI-generated pages with novel component structures appear in the admin review queue | `GET /api/v1/ai/harvest/pending` returns items with `review_status=pending_review` |
| AC-2 | Exactly matching schemas do not create duplicate template definitions | `get_by_schema_signature` is checked before creation |
| AC-3 | Near-matches are flagged with similarity score and matched template reference | `harvest_classification=NEAR_MATCH` and `harvest_matched_type` and `harvest_similarity` populated |
| AC-4 | Admin can preview, edit, and publish a harvested template definition | `PATCH /api/v1/ai/harvest/{id}/publish` sets `is_active=True` |
| AC-5 | Admin can reject a harvested template definition | `DELETE /api/v1/ai/harvest/{id}` returns 204 |
| AC-6 | Admin can merge a near-match into an existing template | `POST /api/v1/ai/harvest/{id}/merge` returns merged result |
| AC-7 | Published harvested templates appear in the template picker UI | Corresponding `TemplateType` record has `is_active=True` |
| AC-8 | Harvested template provenance links back to originating AI session and course | `provenance_json` field contains `sourceSessionId` and `sourceCourseId` |
| AC-9 | Harvest failures do not block page creation | Proposal apply succeeds even if harvest raises an exception |
| AC-10 | Harvest pipeline can be disabled via environment variable | `AI_HARVEST_ENABLED=false` skips harvest entirely |

---

## Section 7 — Task Breakdown

### Chunk 1: Foundation (4-5 days)

| Task ID | Task | File(s) | Effort | Dependencies |
|---|---|---|---|---|
| T1.1 | Add harvest columns to `TemplateDefinition` ORM model | `app/models/persisted_course.py` | 2h | None |
| T1.2 | Create Alembic migration for harvest columns | `alembic/versions/` | 1h | T1.1 |
| T1.3 | Implement `SchemaSimilarityEngine` class | `app/services/ai/template_harvester.py` (new) | 3h | None |
| T1.4 | Implement `TemplateHarvester._harvest_component` method | `app/services/ai/template_harvester.py` | 4h | T1.1, T1.3 |
| T1.5 | Implement `TemplateHarvester.harvest_from_page` orchestrator | `app/services/ai/template_harvester.py` | 3h | T1.4 |
| T1.6 | Add `get_by_schema_signature_list` to `TemplateDefinitionRepository` | `app/repositories/template_definition_repo.py` | 1h | None |
| T1.7 | Unit tests for `SchemaSimilarityEngine` (TH-013 to TH-018) | `tests/test_template_harvester.py` | 2h | T1.3 |
| T1.8 | Unit tests for `TemplateHarvester._harvest_component` (TH-001 to TH-012) | `tests/test_template_harvester.py` | 4h | T1.4 |

### Chunk 2: API and Integration (4-5 days)

| Task ID | Task | File(s) | Effort | Dependencies |
|---|---|---|---|---|
| T2.1 | Create `GET /api/v1/ai/harvest/pending` endpoint | `app/routers/ai_harvest.py` (new) | 3h | T1.1 |
| T2.2 | Create `GET /api/v1/ai/harvest/{id}` endpoint | `app/routers/ai_harvest.py` | 2h | T1.1 |
| T2.3 | Create `PATCH /api/v1/ai/harvest/{id}/publish` endpoint | `app/routers/ai_harvest.py` | 3h | T1.1 |
| T2.4 | Create `DELETE /api/v1/ai/harvest/{id}` endpoint | `app/routers/ai_harvest.py` | 2h | T1.1 |
| T2.5 | Create `POST /api/v1/ai/harvest/{id}/merge` endpoint | `app/routers/ai_harvest.py` | 3h | T1.3 |
| T2.6 | Register `ai_harvest` router in `app/main.py` | `app/main.py` | 0.5h | T2.1 |
| T2.7 | Add auth/permission checks to harvest endpoints | `app/routers/ai_harvest.py` | 2h | None |
| T2.8 | Integrate harvester into proposal apply flow | `app/services/ai/proposal_service.py` | 4h | T1.5, T2.6 |
| T2.9 | API integration tests (API-TH-001 to API-TH-012) | `tests/test_harvest_api.py` | 4h | T2.1-T2.8 |

### Chunk 3: Admin Review UI and Polish (3-4 days)

| Task ID | Task | File(s) | Effort | Dependencies |
|---|---|---|---|---|
| T3.1 | Harvest report in apply response: format and include `harvest` field | `app/services/ai/template_harvester.py` | 3h | T2.8 |
| T3.2 | Implement `AI_HARVEST_ENABLED` guard in proposal apply | `app/services/ai/proposal_service.py` | 1h | T2.8 |
| T3.3 | Implement `AI_HARVEST_MODE` (sync vs async) | `app/services/ai/template_harvester.py` | 2h | T1.5 |
| T3.4 | Implement pending-review count endpoint | `app/routers/ai_harvest.py` | 1h | T2.1 |
| T3.5 | Auto-cleanup unreviewed drafts older than TTL | `app/services/ai/template_harvester.py` (cron job) | 2h | T1.1 |
| T3.6 | Edge case tests (EDGE-001 to EDGE-008) | `tests/test_template_harvester.py` | 3h | Chunk 2 |

### Chunk 4: Outbox Events and Downstream (2-3 days)

| Task ID | Task | File(s) | Effort | Dependencies |
|---|---|---|---|---|
| T4.1 | Emit `TemplateDefinitionHarvested` outbox event on harvest | `app/services/ai/template_harvester.py` | 3h | T1.5, US-AI-033 |
| T4.2 | Emit `TemplateDefinitionPublished` outbox event on publish | `app/routers/ai_harvest.py` | 2h | T2.3, US-AI-033 |
| T4.3 | Update `renderer_manifest.py` to reflect newly published definitions | `app/services/renderer_manifest.py` | 2h | T2.3 |
| T4.4 | Reload renderer registry on publish | `app/routers/ai_harvest.py` (calls `TemplateRegistry.load_definitions`) | 2h | T4.3 |

---

## Section 8 — Dependencies and Risks

### Dependencies

| Dependency | Why | Mitigation |
|---|---|---|
| US-AI-005 (Tool and Template Contract Registry) | Harvested templates must be registered in the tool allowlist to be available for future AI sessions | Design harvester to write to `TemplateDefinition` first; tool allowlist integration is a separate story |
| US-AI-011 (Create Page Proposal and Apply) | Harvest trigger is the proposal apply step | Harvest is best-effort and non-blocking; apply succeeds without harvest |
| US-AI-019 (Full Course from Uploaded File) | Batch course generation triggers harvest for every page | Batch apply should throttle harvest to `AI_HARVEST_MAX_PER_APPLY` |
| US-AI-033 (Event-Driven Outbox) | Outbox events for harvested/published definitions | Events are fire-and-forget; no consumer requires them |

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Harvest creates too many low-quality drafts** | Medium | High (pollutes data) | `AI_HARVEST_MAX_PER_APPLY` cap; always starts as `is_active=False`; TTL auto-cleanup |
| **Similarity engine produces false near-matches** | Medium | Medium (admin noise) | Configurable `AI_HARVEST_SIMILARITY_THRESHOLD`; field-level diff in review UI |
| **Harvest latency blocks apply response** | Low | Medium (UX delay) | `AI_HARVEST_MODE=asynchronous` for production; synchronous mode has 2s timeout |
| **Schema signature collision** | Very Low | Low (SHA-256 collision risk negligible) | N/A — SHA-256 is collision-resistant for this use case |
| **Admin never reviews pending drafts** | High | Low (stale data) | TTL auto-cleanup (`AI_HARVEST_DRAFT_TTL_DAYS`); admin notification on queue size |
| **Concurrent harvest of same novel schema** | Low | Low (duplicate attempt) | First writer creates signature; second writer detects EXACT_MATCH; unique constraint on `schema_signature` in DB |

### Release Criteria

| Phase | Criteria | Includes |
|---|---|---|
| **Dev complete** | All Chunk 1-2 tasks done | Backend harvest pipeline, API endpoints, unit + integration tests |
| **QA** | All acceptance criteria pass | AC-1 through AC-10 verified |
| **Staging** | Admin review workflow functional | Publish/merge/reject flows work end-to-end |
| **Production** | Harvest enabled with conservative settings | `AI_HARVEST_MODE=asynchronous`, `AI_HARVEST_MAX_PER_APPLY=5`, `AI_HARVEST_REVIEW_REQUIRED=true` |

### Operational Runbook

**On-call engineers should know:**
1. Harvest runs inline with proposal apply (sync mode) or as a background job (async mode)
2. Harvest failures are logged at WARNING level and never block the user
3. Pending drafts can be monitored via `GET /api/v1/ai/harvest/pending?review_status=pending_review`
4. Auto-cleanup runs daily and deletes drafts older than `AI_HARVEST_DRAFT_TTL_DAYS`
5. To disable harvest entirely, set `AI_HARVEST_ENABLED=false` and restart
6. A large number of pending drafts (>1000) may slow the review endpoint — pagination is enforced

**Key log lines to watch:**
```
[INFO] TemplateHarvester - Harvested 3 components from page page-123 (session uuid): 1 exact, 1 near, 1 novel
[WARNING] TemplateHarvester - Harvest failed for component accordion: DB connection error
[INFO] TemplateHarvester - Published harvested definition harvested_accordion_a1b2 as active template
[WARNING] TemplateHarvester - Auto-cleanup deleted 12 unreviewed drafts older than 90 days
```
