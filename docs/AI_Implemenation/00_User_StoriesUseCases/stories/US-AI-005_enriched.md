# US-AI-005: Version Tool Schemas and Template Contracts

**Priority:** MUST  
**Depends on:** US-AI-003 (Create Isolated AI API Module)  
**Unlocks:** Tool Calls, Validation Pipeline, AI Authoring  
**Estimated Size:** XL (~5-7 days)  

---

## 1. FUNCTIONAL SPECIFICATION

### 1.1 User Story

As an AI course authoring agent (Claude), I need a versioned, validated set of tool schemas and template contracts so that I can reliably generate tool calls that the backend validates, executes, and returns results for -- ensuring that every page I create or modify conforms to an exact data contract, and that the system prompt tells me exactly which tools are available and what their input/output shapes are.

### 1.2 Numbered Functional Requirements

**FR-1: Tool Schema Registry**  
The system shall maintain a versioned registry of all AI-accessible tool definitions (name, description, input_schema, output_schema, idempotency flag, permission_scope). The registry shall be the single source of truth from which both the Claude system prompt tool definitions and the server-side validation are derived.

**FR-2: Template Contract Definitions**  
The system shall define five canonical template contracts -- `text-content`, `tabs`, `accordion`, `click-reveal`, and `final-assessment` -- with exact JSON Schema specifications for each. Each contract shall specify required fields, allowed field types, min/max constraints, and nested structure rules.

**FR-3: Schema Versioning**  
Every template contract and tool schema shall carry a semantic version (MAJOR.MINOR.PATCH). A schema_signature SHA-256 hash shall be computed over the canonical JSON Schema definition. Version bumps require a new signature; minor bumps (backward-compatible additions) share the same signature.

**FR-4: Server-Side Schema Validation Engine**  
A dedicated schema validation service shall accept a (template_type, data_payload) pair and return a `ValidationResult` containing errors (blocking), warnings (non-blocking), and info messages. The engine shall use the registered schema for the template type, not RAG or LLM-inferred validation.

**FR-5: Template Registry Query API**  
The system shall expose an API endpoint that returns the full list of registered template contracts, including their JSON Schema, current version, schema signature, and allowed enum values. The AI session prompt builder shall consume this API at session start to embed the current contract set into the system prompt.

**FR-6: Tool Schema Generation from Template Contracts**  
Each template contract shall auto-generate the Claude tool input_schema for the `propose_create_page` and `propose_update_page` tools. When a new template type is added, the tool schemas automatically reflect it without code changes to the tool definitions themselves.

**FR-7: Cross-Template Business Rule Validation**  
Beyond field-level JSON Schema validation, the system shall enforce cross-template business rules: `final-assessment` requires minimum 3 questions; `tabs` requires 2-6 tabs; `accordion` requires 2-20 items; `click-reveal` requires 2-10 items; question types must be one of `multiple_choice | true_false | fill_in | multi_select`.

**FR-8: Template Contract Migration Support**  
When a template contract version is updated, the system shall support a migration path: old data (with the previous schema_signature) remains renderable but is flagged as "uses legacy schema." A migration utility shall transform legacy data to the current schema shape on explicit upgrade request.

**FR-9: Error Code Catalog for Tool Validation**  
All validation failures shall return a machine-readable error code from a predefined catalog (e.g., `MISSING_REQUIRED_FIELD`, `MIN_LENGTH_VIOLATION`, `MAX_ITEMS_EXCEEDED`, `INVALID_ENUM_VALUE`, `SCHEMA_SIGNATURE_MISMATCH`, `BUSINESS_RULE_VIOLATION`). The error catalog shall be documented and versioned.

**FR-10: Tool Call Auditing**  
Every tool call received by the backend (whether valid or invalid) shall be logged with: tool name, input payload hash, validation result, processing duration, session ID, user ID, and timestamp. Invalid calls shall log the specific error code.

### 1.3 Step-by-Step User Flow

#### Happy Path: AI Creates a Page via Tool Call

```
1. AI Agent sends: propose_create_page({ session_id, title, template_type: "tabs", data: {...} })
2. Backend validates session exists and is active (FR-2 from US-AI-003)
3. Backend resolves template_type "tabs" from TemplateRegistry (FR-5)
4. Backend loads the registered JSON Schema for "tabs" (FR-2)
5. Schema validation engine runs:
   a. Check data is valid JSON
   b. Validate against JSON Schema (FR-4)
   c. Enforce business rules: tabs array has 2-6 items, each tab has title+content (FR-7)
6. Validation succeeds -> status: "valid"
7. Backend creates a proposal record (no mutation yet)
8. Backend returns: proposal_id, preview, validation_status: "valid", validation_messages: []
9. Audit log: tool="propose_create_page", input_hash="abc123", result="valid" (FR-10)
```

#### Alternate Path: Validation Fails

```
1. AI Agent sends: propose_create_page({ session_id, title, template_type: "final-assessment", data: {title: "Quiz", passing_score: 70, questions: [...]} })
2. Backend resolves schema for "final-assessment"
3. Schema validation: questions array has only 2 items
4. Business rule: "final-assessment requires minimum 3 questions" -> violation (FR-7)
5. Backend returns: validation_status: "error", validation_messages: [{severity: "error", field: "data.questions", message: "...", code: "BUSINESS_RULE_VIOLATION"}]
6. Audit log: tool="propose_create_page", input_hash="def456", result="error", code="BUSINESS_RULE_VIOLATION" (FR-10)
7. AI Agent receives error, adjusts data (adds 3rd question), retries
```

#### Alternate Path: Unknown Template Type

```
1. AI Agent sends propose_create_page with template_type: "drag-and-drop" (not registered)
2. Backend tries to resolve template_type -> not found
3. Returns: validation_status: "error", validation_messages: [{severity: "error", field: "template_type", message: "Unknown template type: drag-and-drop", code: "INVALID_ENUM_VALUE"}]
4. AI Agent must fall back to a known type or ask user
```

#### Error Path: Expired Session

```
1. AI Agent sends tool call with stale/invalid session_id
2. Backend session validation fails
3. Returns: standard error shape { status: "error", code: "PERMISSION_DENIED", message: "Session expired", retryable: true }
4. AI Agent must create new session -> restart
```

### 1.4 UI/UX Requirements

This story is primarily backend infrastructure. The relevant UI elements are:
- A "Template Contracts" admin view (future sprint) showing all registered templates, versions, and schema signatures.
- AI session status indicators that show "v1.2.0" tool schema version in use (visible in developer debug mode).
- Validation error display in the AI Chat Panel: errors shown inline with field paths and codes, warnings shown as amber banners.
- The propose-apply confirmation modal already defined in UI/UX for US-AI-003.

---

## 2. TECHNICAL SPECIFICATION

### 2.1 API Contracts

#### 2.1.1 GET /api/v1/ai/templates -- List Template Contracts

```
Method: GET
Path: /api/v1/ai/templates
Headers:
  Authorization: Session {sessionId}
  Accept: application/json

Query Parameters:
  include_legacy: boolean (optional, default false) -- include deprecated/legacy contracts

Response 200:
{
  "version": "1.0.0",
  "generated_at": "2026-06-14T12:00:00Z",
  "templates": [
    {
      "type_key": "text-content",
      "display_name": "Text Content",
      "version": "1.0.0",
      "schema_signature": "a1b2c3d4e5f6...64chars",
      "is_active": true,
      "allowed": true,
      "validation_rules": {
        "required_fields": ["title", "content"],
        "optional_fields": ["key_points"],
        "max_length": {"title": 200},
        "constraints": {}
      }
    },
    {
      "type_key": "tabs",
      "display_name": "Tabs",
      "version": "1.0.0",
      "schema_signature": "b2c3d4e5f6a7...64chars",
      "is_active": true,
      "allowed": true,
      "validation_rules": {
        "required_fields": ["title", "tabs"],
        "optional_fields": [],
        "max_length": {"title": 200, "tabs[].title": 50},
        "constraints": {
          "tabs": {"min_items": 2, "max_items": 6}
        }
      }
    },
    {
      "type_key": "accordion",
      "display_name": "Accordion",
      "version": "1.0.0",
      "schema_signature": "c3d4e5f6a7b8...64chars",
      "is_active": true,
      "allowed": true,
      "validation_rules": {
        "required_fields": ["title", "items"],
        "optional_fields": [],
        "constraints": {
          "items": {"min_items": 2, "max_items": 20}
        }
      }
    },
    {
      "type_key": "click-reveal",
      "display_name": "Click to Reveal",
      "version": "1.0.0",
      "schema_signature": "d4e5f6a7b8c9...64chars",
      "is_active": true,
      "allowed": true,
      "validation_rules": {
        "required_fields": ["title", "items"],
        "optional_fields": [],
        "constraints": {
          "items": {"min_items": 2, "max_items": 10}
        }
      }
    },
    {
      "type_key": "final-assessment",
      "display_name": "Final Assessment",
      "version": "1.0.0",
      "schema_signature": "e5f6a7b8c9d0...64chars",
      "is_active": true,
      "allowed": true,
      "validation_rules": {
        "required_fields": ["title", "passing_score", "questions"],
        "optional_fields": [],
        "constraints": {
          "passing_score": {"min": 0, "max": 100},
          "questions": {"min_items": 3, "max_items": 50}
        }
      }
    }
  ]
}

Response 401:
{ "status": "error", "code": "PERMISSION_DENIED", "message": "Session invalid or expired" }

Response 503:
{ "status": "error", "code": "SERVER_ERROR", "message": "Template registry unavailable", "retryable": true }
```

#### 2.1.2 GET /api/v1/ai/templates/{type_key} -- Get Single Template Contract

```
Method: GET
Path: /api/v1/ai/templates/{type_key}
Headers:
  Authorization: Session {sessionId}

Response 200:
{
  "type_key": "tabs",
  "display_name": "Tabs",
  "version": "1.0.0",
  "schema_signature": "b2c3d4e5f6a7...64chars",
  "is_active": true,
  "allowed": true,
  "json_schema": {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["title", "tabs"],
    "properties": {
      "title": {"type": "string", "maxLength": 200},
      "tabs": {
        "type": "array",
        "minItems": 2,
        "maxItems": 6,
        "items": {
          "type": "object",
          "required": ["title", "content"],
          "properties": {
            "title": {"type": "string", "maxLength": 50},
            "content": {"type": "string"},
            "icon": {"type": "string"}
          }
        }
      }
    }
  },
  "business_rules": [],
  "created_at": "2026-06-13T00:00:00Z",
  "updated_at": "2026-06-13T00:00:00Z"
}

Response 404:
{ "status": "error", "code": "NOT_FOUND", "message": "Template type 'unknown-type' not found" }
```

#### 2.1.3 POST /api/v1/ai/tools/validate -- Validate Template Data (Standalone)

```
Method: POST
Path: /api/v1/ai/tools/validate
Headers:
  Authorization: Session {sessionId}
  Content-Type: application/json

Request Body:
{
  "session_id": "uuid",
  "template_type": "tabs",
  "data": {
    "title": "Cloud Providers Comparison",
    "tabs": [
      {"title": "AWS", "content": "Amazon Web Services..."},
      {"title": "Azure", "content": "Microsoft Azure..."}
    ]
  },
  "validation_scope": "full"
}

Response 200:
{
  "status": "valid",
  "schema_status": "valid",
  "business_rules_status": "valid",
  "validation_messages": [],
  "schema_signature": "b2c3d4e5f6a7...64chars",
  "template_version": "1.0.0"
}

Response 200 (with warnings):
{
  "status": "warning",
  "schema_status": "valid",
  "business_rules_status": "warning",
  "validation_messages": [
    {
      "severity": "warning",
      "code": "OPTIONAL_FIELD_MISSING",
      "field": "data.tabs[0].icon",
      "message": "Icon field recommended for tab content",
      "hint": "Add icon name to improve visual distinction"
    }
  ],
  "schema_signature": "b2c3d4e5f6a7...64chars",
  "template_version": "1.0.0"
}

Response 200 (with errors):
{
  "status": "error",
  "schema_status": "valid",
  "business_rules_status": "error",
  "validation_messages": [
    {
      "severity": "error",
      "code": "MIN_ITEMS_VIOLATION",
      "field": "data.tabs",
      "message": "Tabs must have at least 2 items, got 1",
      "hint": "Add another tab or use text-content template",
      "min": 2,
      "actual": 1
    }
  ],
  "schema_signature": null,
  "template_version": null
}
```

All HTTP status codes used:
- 200: Validation succeeded (schema + business rules) -- check `status` field for valid/warning/error
- 400: Malformed request body, missing required fields
- 401: Authentication/authorization failure
- 422: Request validation error (FastAPI Pydantic rejection)
- 404: Template type not found
- 503: Registry unavailable

### 2.2 Database Schema DDL

#### 2.2.1 Table: `tool_schema_registry`

```sql
CREATE TABLE tool_schema_registry (
    id                    SERIAL PRIMARY KEY,
    tool_name             VARCHAR(100) NOT NULL UNIQUE,
    tool_version          VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    schema_signature      VARCHAR(64) NOT NULL,  -- SHA-256 of tool definition JSON
    is_idempotent         BOOLEAN NOT NULL DEFAULT FALSE,
    permission_scope      VARCHAR(100) NOT NULL DEFAULT 'session.course_id',
    input_schema_json     JSONB NOT NULL,
    output_schema_json    JSONB NOT NULL,
    description           TEXT NOT NULL DEFAULT '',
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tool_schema_active ON tool_schema_registry(is_active);
CREATE INDEX idx_tool_schema_signature ON tool_schema_registry(schema_signature);
```

#### 2.2.2 Table: `template_contracts`

```sql
CREATE TABLE template_contracts (
    id                    SERIAL PRIMARY KEY,
    type_key              VARCHAR(100) NOT NULL UNIQUE,
    display_name          VARCHAR(200) NOT NULL,
    version               VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    schema_signature      VARCHAR(64) NOT NULL,  -- SHA-256 of json_schema
    json_schema           JSONB NOT NULL,         -- Full JSON Schema draft-07
    business_rules        JSONB NOT NULL DEFAULT '[]'::JSONB,  -- Array of rule objects
    renderer_class        VARCHAR(255),
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    is_deprecated         BOOLEAN NOT NULL DEFAULT FALSE,
    deprecated_by         VARCHAR(100),            -- type_key of replacement
    predecessor_signature VARCHAR(64),             -- signature this replaced
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_template_contracts_active ON template_contracts(is_active);
CREATE INDEX idx_template_contracts_signature ON template_contracts(schema_signature);
CREATE UNIQUE INDEX idx_template_contracts_type_active 
    ON template_contracts(type_key) WHERE is_active = TRUE;
```

#### 2.2.3 Table: `template_data_migrations`

```sql
CREATE TABLE template_data_migrations (
    id                    SERIAL PRIMARY KEY,
    page_id               VARCHAR(64) NOT NULL,
    template_type         VARCHAR(100) NOT NULL,
    from_signature        VARCHAR(64) NOT NULL,
    to_signature          VARCHAR(64) NOT NULL,
    from_version          VARCHAR(20) NOT NULL,
    to_version            VARCHAR(20) NOT NULL,
    migrated_data         JSONB NOT NULL,          -- The transformed data
    status                VARCHAR(20) NOT NULL DEFAULT 'pending',
        -- 'pending', 'in_progress', 'completed', 'failed'
    error_message         TEXT,
    triggered_by          VARCHAR(100) NOT NULL,   -- 'auto' or 'user_initiated'
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at          TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_template_migrations_page ON template_data_migrations(page_id);
CREATE INDEX idx_template_migrations_status ON template_data_migrations(status);
```

**Migration Note:** The existing `template_definitions` table (in `app.models.persisted_course.TemplateDefinition`) already stores template schemas. The new `template_contracts` table adds the versioning, signature, business rules, and deprecation tracking. A startup migration should copy records from `template_definitions` into `template_contracts` where they don't exist. The `template_definitions` table remains as the rendering/export schema source; `template_contracts` is the AI contract source.

### 2.3 Service/Module Design

#### 2.3.1 New Module: `app/services/ai/tool_registry.py`

```python
class ToolRegistry:
    """Versioned registry of all AI-accessible tool definitions."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_tool(self, tool_name: str) -> Optional[dict]:
        """Retrieve a single tool definition by name."""

    async def list_tools(self, *, active_only: bool = True) -> list[dict]:
        """Return all registered tool definitions."""

    async def compute_schema_signature(self, tool_def: dict) -> str:
        """Compute SHA-256 over the canonical tool definition JSON (sorted keys)."""

    async def register_tool(self, tool_def: dict) -> dict:
        """Insert or update a tool definition."""

    async def deregister_tool(self, tool_name: str) -> None:
        """Soft-delete (is_active=False) a tool definition."""

    async def get_system_prompt_tools_block(self) -> list[dict]:
        """Return only the subset of tools suitable for the Claude system prompt.
        Filters out internal-only tools.
        """
```

#### 2.3.2 New Module: `app/services/ai/template_registry.py`

```python
class TemplateRegistry:
    """Registry of all template contracts with versioning and validation."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_contract(self, type_key: str) -> Optional[TemplateContract]:
        """Retrieve the active contract for a template type."""

    async def list_contracts(self, *, include_legacy: bool = False) -> list[TemplateContract]:
        """List all template contracts (active only by default)."""

    async def register_contract(self, contract: TemplateContract) -> TemplateContract:
        """Register a new template contract version."""

    async def deprecate_contract(self, type_key: str, replacement_key: str) -> None:
        """Mark a contract as deprecated and point to its replacement."""

    async def get_schema_for_type(self, type_key: str) -> Optional[dict]:
        """Get the JSON Schema for the active version of a template type."""

    async def get_business_rules(self, type_key: str) -> list[dict]:
        """Get the business rules for a template type."""

    def compute_signature(self, schema: dict) -> str:
        """Compute SHA-256 over canonical JSON Schema."""
```

#### 2.3.3 New Module: `app/services/ai/validation_engine.py`

```python
class TemplateValidationEngine:
    """Validation engine: JSON Schema + business rules for template data."""

    def __init__(self, template_registry: TemplateRegistry):
        self.template_registry = template_registry

    async def validate(
        self,
        template_type: str,
        data: dict,
        scope: Literal["schema_only", "business_rules", "full"] = "full",
    ) -> ValidationResult:
        """Validate template data against schema and business rules.
        
        Returns a ValidationResult with:
        - status: "valid" | "warning" | "error"
        - schema_status: "valid" | "error"
        - business_rules_status: "valid" | "warning" | "error"
        - messages: list of ValidationMessage
        - schema_signature: str | None
        - template_version: str | None
        """

    async def validate_schema(self, template_type: str, data: dict) -> SchemaValidationResult:
        """JSON Schema validation only."""

    async def validate_business_rules(
        self, template_type: str, data: dict
    ) -> list[ValidationMessage]:
        """Business-rule validation only (after schema passes)."""

    def _build_validation_message(
        self,
        severity: str,
        code: str,
        field: str,
        message: str,
        hint: str = None,
        **extra,
    ) -> dict:
        """Build a standardized validation message dict."""


class ValidationResult:
    status: str  # "valid", "warning", "error"
    schema_status: str
    business_rules_status: str
    messages: list[ValidationMessage]
    schema_signature: Optional[str]
    template_version: Optional[str]


class ValidationMessage:
    severity: str  # "error", "warning", "info"
    code: str      # From error code catalog
    field: str     # JSON path like "data.questions[0].options"
    message: str   # Human-readable
    hint: Optional[str]
    # Extra fields per code (min, max, actual, etc.)
```

#### 2.3.4 Updates to Existing Module: `app/services/ai/__init__.py`

```python
# New exports for the AI layer
from app.services.ai.tool_registry import ToolRegistry
from app.services.ai.template_registry import TemplateRegistry
from app.services.ai.validation_engine import (
    TemplateValidationEngine,
    ValidationResult,
    ValidationMessage,
)
```

#### 2.3.5 Router: `app/routers/ai_templates.py`

```python
router = APIRouter(prefix="/api/v1/ai/templates", tags=["AI Templates"])

@router.get("")
async def list_template_contracts(
    include_legacy: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    registry: TemplateRegistry = Depends(get_template_registry),
):
    """FR-5: Return all registered template contracts."""
    contracts = await registry.list_contracts(include_legacy=include_legacy)
    return {
        "version": "1.0.0",
        "generated_at": datetime.utcnow().isoformat(),
        "templates": [c.to_api_dict() for c in contracts],
    }

@router.get("/{type_key}")
async def get_contract_detail(
    type_key: str,
    session: AsyncSession = Depends(get_session),
    registry: TemplateRegistry = Depends(get_template_registry),
):
    """FR-5: Return full contract details including JSON Schema."""
    contract = await registry.get_contract(type_key)
    if not contract:
        raise HTTPException(status_code=404, detail=f"Template type '{type_key}' not found")
    return contract.to_detail_dict()
```

### 2.4 Configuration Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `AI_TOOL_SCHEMA_VERSION` | `str` | `"1.0.0"` | Current tool schema version string, embedded in system prompt |
| `AI_TEMPLATE_CONTRACT_REFRESH_INTERVAL` | `int` | `300` | Seconds between cache refreshes of the template contract registry |
| `AI_VALIDATION_MAX_RETRIES` | `int` | `2` | Max automatic validation retry attempts per proposal |
| `AI_SCHEMA_SIGNATURE_ALGORITHM` | `str` | `"sha256"` | Hash algorithm for schema signatures |
| `AI_TEMPLATE_CONTRACT_MAX_CACHE_SIZE` | `int` | `100` | Max entries in in-memory contract cache |
| `AI_ERROR_CODE_CATALOG_PATH` | `str` | `"./config/error_codes.json"` | Path to the error code catalog file |

### 2.5 Integration Points

**Repositories (existing, reused):**
- `TemplateDefinitionRepository` (`app/repositories/template_definition_repo.py`) -- used to read existing template definitions for the migration into the new `template_contracts` table.
- `ComponentTypeRepository` (`app/repositories/component_type_repo.py`) -- the component_type JSON schema can be cross-referenced with template contracts for consistency.

**New Repositories:**
- `ToolSchemaRepository` -- CRUD for `tool_schema_registry` table.
- `TemplateContractRepository` -- CRUD for `template_contracts` table.
- `TemplateDataMigrationRepository` -- CRUD for `template_data_migrations` table.

**External Services:**
- None directly; this story is entirely backend-internal.

**Events:**
- `template_contract_registered` -- emitted when a new template contract version is registered.
- `template_contract_deprecated` -- emitted when a contract is deprecated.
- `tool_schema_updated` -- emitted when tool schemas change (triggers prompt rebuild).

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### 3.1 Performance

| Metric | Target | Measurement |
|---|---|---|
| Template contract registry lookup (p50) | < 10ms | Direct DB lookup by type_key index |
| Template contract registry lookup (p95) | < 30ms | With in-memory LRU cache of size 100 |
| Schema validation (p50) | < 50ms | JSON Schema validation in Python |
| Schema validation (p95) | < 150ms | For 50-question final-assessment payloads |
| Business rule validation (p50) | < 20ms | Rule evaluation is O(n) over data items |
| Full validate call (p99) | < 500ms | Combined schema + business rules |
| Tool schema generation from registry | < 100ms | Building system prompt tools block |
| Template contract list API (p95) | < 200ms | With pagination and caching |
| Throughput | >= 100 validations/second | Single instance, no replication |

### 3.2 Security

**Authorization Model:**
- Template contract listing is authenticated but not course-scoped (any authorized user can list contracts).
- Tool validation endpoints are session-scoped (requires valid session from US-AI-003).
- Schema definition modifications (register, deprecate) require admin role -- NOT in scope for this story, but the `is_active` field and API endpoints should be wired to accept admin-only middleware in a follow-up.

**Validation Rules:**
- All template data payloads are sanitized: HTML content in string fields must pass through an allowlist-based sanitizer (no script tags, no event handlers, no `javascript:` URIs).
- Maximum payload size for template data: 512 KB.
- Field length limits enforced at both JSON Schema level and database level (String(200), etc.).

**Tenant Isolation:**
- Template contracts are global (shared across all organizations in the multi-tenant setup).
- Template data migrations are specific to pages, which are course-scoped (course-scoped by `course_id` FK through `page_id`).

### 3.3 Reliability

**Error Codes Catalog:**

| Code | HTTP Status | Description | Retryable |
|---|---|---|---|
| `MISSING_REQUIRED_FIELD` | 200 (validation error) | Required field absent from data payload | Yes |
| `MIN_LENGTH_VIOLATION` | 200 | String shorter than minimum | Yes |
| `MAX_LENGTH_VIOLATION` | 200 | String exceeds maximum | Yes |
| `MIN_ITEMS_VIOLATION` | 200 | Array has fewer than minimum items | Yes |
| `MAX_ITEMS_VIOLATION` | 200 | Array exceeds maximum items | Yes |
| `INVALID_ENUM_VALUE` | 200 | Value not in allowed enum | Yes |
| `INVALID_TYPE` | 200 | Value has wrong JSON type | Yes |
| `SCHEMA_SIGNATURE_MISMATCH` | 200 | Data structure doesn't match registered schema | Yes |
| `BUSINESS_RULE_VIOLATION` | 200 | Cross-field or semantic rule broken | Yes |
| `INVALID_ENUM_VALUE` | 404 | Unknown template type | No |
| `TEMPLATE_TYPE_NOT_FOUND` | 404 | Template type not in registry | No |
| `PERMISSION_DENIED` | 401 | Session expired or invalid | True (re-auth) |
| `VALIDATION_ENGINE_ERROR` | 503 | Internal schema engine failure | Yes |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many validation calls | Yes (after delay) |

**Retry Strategy:**
- Clients (AI Agent) should retry on `retryable: true` errors, up to `AI_VALIDATION_MAX_RETRIES` (default 2).
- Retry should use exponential backoff: 1s, 4s. Do not retry after the third failure -- escalate to user.
- Non-retryable errors (`TEMPLATE_TYPE_NOT_FOUND`, `PERMISSION_DENIED`) should not be retried.

**Graceful Degradation:**
- If the `template_contracts` table is unreachable, the system falls back to a hardcoded minimal set of 5 contract definitions (loaded from a JSON file at `./config/fallback_contracts.json`). This ensures the AI layer can still function during DB outages -- validation is less strict but non-blocking.
- The fallback contracts have `is_active: true` but `schema_signature: "FALLBACK"` to distinguish them in logs.
- If the `tool_schema_registry` table is unreachable, the system falls back to the 12 tool definitions from `TOOL_SCHEMAS_CLAUDE_NATIVE.md` (embedded as a JSON asset in the deployment).

**Idempotency Guarantees:**
- `GET /api/v1/ai/templates` -- idempotent by nature.
- `POST /api/v1/ai/tools/validate` -- idempotent; same input always returns same validation result (pure function: schema + business rules are deterministic).
- Tool schema registration is idempotent via `tool_name` UNIQUE constraint (upsert pattern).

### 3.4 Scalability

- The tool registry and template registry are **stateless** -- all data lives in PostgreSQL. Any pod can serve any request.
- In-memory caching (LRU with `AI_TEMPLATE_CONTRACT_MAX_CACHE_SIZE=100`) reduces DB load but is disposable on pod restart.
- The validation engine is CPU-bound for large payloads (50-question assessments). For horizontal scaling, validation can be offloaded to background workers using a task queue if p99 exceeds 500ms.
- Connection pooling: use the existing `AsyncSession` pool (`app/db/config.py`). Each validation call acquires a connection briefly (for template contract lookup), holds it for < 30ms p50, then releases.

---

## 4. CURRENT STATE ASSESSMENT

### 4.1 What Exists in the Codebase Today (Reusable)

| File/Component | What It Provides | How to Reuse |
|---|---|---|
| `app/models/persisted_course.py` `TemplateDefinition` class | ORM model for `template_definitions` table with `template_type`, `schema_signature`, `render_template_html`, `schema_json`, `is_active` | Schema definition patterns and DB column conventions; seed data migration source |
| `app/models/persisted_course.py` `TemplateRecord` class | ORM model for `templates` table with `template_uid`, `template_type`, `schema_signature`, `title`, `order_index`, `json_data` | The `template_type` and `schema_signature` fields establish the FK pattern for template data referencing its schema |
| `app/models/template_schema.py` `TemplateDefinition` Pydantic model | Pydantic validation model with `FieldSchema`, `RenderConfig`, `ScormBehavior`, `SanitizeRules` | Field-level validation model can be reused or adapted for the new `TemplateContract` Pydantic model |
| `app/models/component_type.py` `ComponentType` class | ORM registry with `type_id`, `schema` (JSONB), `is_active` | The schema field and registry pattern is directly analogous to `template_contracts.json_schema` |
| `app/repositories/template_definition_repo.py` | Full async repository for `TemplateDefinition` with `get_by_type_key`, `list_all`, `create`, `exists` | Reuse `get_by_type_key` as source for the migration; adapt `_coerce_schema_json` and `_derive_field_schema` helpers |
| `app/repositories/component_type_repo.py` | Async repository with `list`, `get_by_type_id`, `search`, `upsert`, `bulk_upsert` | The `upsert` and `bulk_upsert` patterns for the new `ToolSchemaRepository` and `TemplateContractRepository` |
| `app/services/seed_template_types.py` | Startup seed script for `template_definitions` | Augment to also seed `template_contracts` table |
| `app/services/seed_component_types.py` | Startup seed script for `component_types` | Pattern reference for seeding tool schemas at startup |
| `app/models/template_type.py` | `TemplateType` model | Enum/string constants for the 5 template types |
| `app/db/config.py` | `get_session` dependency, `AsyncSession`, `engine` | Reuse directly for all new repositories |
| `app/routers/templates.py` | Existing template CRUD with `TemplateCreate`, `TemplateUpdate`, error handling | Pydantic DTO patterns, error handling patterns |
| `docs/AI_Implemenation/01_SystemArchitecture/TOOL_SCHEMAS_CLAUDE_NATIVE.md` | Complete specification of 12 tools with input/output schemas | Source of truth for tool definitions to seed the `tool_schema_registry` table |
| `app/models/export_contract.py` | Pydantic `ExportedComponent`, `ExportedPage`, `RendererManifest` | Contract patterns for component data serialization; `RendererManifest.get_supported_types()` |

### 4.2 What Must Be Built Net-New

| Component | Files to Create |
|---|---|
| Tool Schema Registry service | `app/services/ai/tool_registry.py` |
| Template Registry service | `app/services/ai/template_registry.py` |
| Validation Engine service | `app/services/ai/validation_engine.py` |
| Tool Schema Repository | `app/repositories/ai/tool_schema_repo.py` or generic `app/repositories/ai/` dir |
| Template Contract Repository | `app/repositories/ai/template_contract_repo.py` |
| Template Data Migration Repository | `app/repositories/ai/template_migration_repo.py` |
| Template Contracts router | `app/routers/ai_templates.py` |
| Tool Validate router (or extend existing) | Add validate endpoint to existing `app/routers/ai_tools.py` (from US-AI-003) |
| DB migration Alembic script | `alembic/versions/xxxx_add_template_contracts.py` |
| Pydantic models for contracts | `app/models/ai/template_contract.py` |
| Pydantic models for validation results | `app/models/ai/validation_result.py` |
| Error code catalog JSON | `config/error_codes.json` |
| Fallback contracts JSON | `config/fallback_contracts.json` |

### 4.3 What Existing Code Must Be Modified (with Non-Regression Constraints)

| File | Modification | Non-Regression Constraint |
|---|---|---|
| `app/main.py` | Register the new `ai_templates` router | Existing routers unchanged; new import added to `routers` list; lifespan startup seeding must not error on existing rows |
| `app/services/seed_template_types.py` | Augment to also insert into `template_contracts` table alongside the existing `template_definitions` insert | Must not break the existing template definition seeding -- the `template_definitions` table is still the source of truth for rendering and export |
| `app/services/ai/__init__.py` | Export new service classes | No existing imports break; this file currently exports nothing AI-specific (it may not even exist yet; US-AI-003 creates the `app/services/ai/` package) |
| Alembic `env.py` | Ensure new models are imported for autogenerate | Must not alter existing table detection |
| (future) `app/services/ai/prompt_builder.py` | Will consume `ToolRegistry.get_system_prompt_tools_block()` at session creation | This is a future integration point (US-AI-006), not this story |

**Critical non-regression:** The existing `POST /api/v1/ai/tools/propose_create_page` (from US-AI-003) must still work after this story. It will internally call the new `TemplateValidationEngine.validate()` instead of inline validation. The response shape must be identical -- this is a refactoring of the validation internals, not the public API.

---

## 5. EXPANSION POINTS

### 5.1 Technical Extensions (Future Sprints)

**TX-1: Schema Hot-Reload Without Deployment**  
The registry could be extended with a WebSocket endpoint that pushes contract updates to connected AI sessions in real time, so the system prompt tools block refreshes without requiring session restart.

**TX-2: Template Contract Testing Framework**  
A dedicated API endpoint to submit test payloads against a template contract and see exhaustive validation results (including edge cases). Useful for template authors during contract authoring.

**TX-3: Contract DRY Validation with OpenAPI Spec**  
Instead of manually maintaining `input_schema` in the tool registry, generate it directly from the OpenAPI 3.1 spec by parsing `operation.requestBody.content['application/json'].schema` -- eliminating manual drift entirely.

**TX-4: Multi-Version Active Contracts**  
Support multiple active versions of a template contract simultaneously (e.g., v1.0 and v1.1 both active). The validation engine selects which version to use based on the page's stored `schema_signature` or a session-level parameter.

**TX-5: Contract Dependency Graph**  
Some templates may depend on shared sub-schemas (e.g., `question` sub-schema reused by `final-assessment` and `quiz`). Implement a `$ref`-style dependency resolution in the registry.

### 5.2 Functional Extensions (Future Sprints)

**FX-1: Custom Template Contracts**  
Allow power users or org admins to author custom template contracts via a UI, which get registered in `template_contracts` and immediately become available to the AI agent (without code deploy). Requires a contract builder UI and an admin approval workflow.

**FX-2: Template Contract Analytics**  
Track which template contracts are most used by the AI agent, average validation pass/fail rates per contract, and common validation errors. Surfaces quality improvements for contract definitions.

**FX-3: SCORM Compliance Annotation in Contracts**  
Each template contract can declare its SCORM interaction type (none, choice, fill-in, true-false, matching) and scoring configuration. The validation engine could add SCORM compliance validation to the business rules layer.

**FX-4: WCAG Accessibility Validation in Business Rules**  
Add per-template WCAG checks (e.g., "all images in accordion content must have alt text", "color contrast ratios in final-assessment must be >= 4.5:1"). These would be optional "warning" severity rules initially.

---

## 6. VALIDATION & TESTING

### 6.1 Unit Test Scenarios

**UT-1: Schema Validation -- Valid Payload**  
- Input: `validate("tabs", {"title": "Compare", "tabs": [{"title": "A", "content": "AAA"}, {"title": "B", "content": "BBB"}]})`
- Expected: `ValidationResult(status="valid", schema_status="valid", business_rules_status="valid", messages=[])`

**UT-2: Schema Validation -- Missing Required Field**  
- Input: `validate("text-content", {"title": "Intro"})` (missing `content`)
- Expected: `ValidationResult(status="error", schema_status="error", messages=[{severity: "error", code: "MISSING_REQUIRED_FIELD", field: "data.content"}])`

**UT-3: Business Rule -- Assessment Too Few Questions**  
- Input: `validate("final-assessment", {"title": "Quiz", "passing_score": 70, "questions": [q1, q2]})` (only 2 questions)
- Expected: `ValidationResult(status="error", business_rules_status="error", messages=[{severity: "error", code: "MIN_ITEMS_VIOLATION", field: "data.questions", min: 3, actual: 2}])`

**UT-4: Business Rule -- Passing Score Out of Range**  
- Input: `validate("final-assessment", {"title": "Quiz", "passing_score": 150, "questions": [q1, q2, q3]})`
- Expected: `ValidationResult(status="error", messages=[{severity: "error", code: "BUSINESS_RULE_VIOLATION", field: "data.passing_score", min: 0, max: 100, actual: 150}])`

**UT-5: Business Rule -- Tabs Too Few Items**  
- Input: `validate("tabs", {"title": "Compare", "tabs": [{"title": "A", "content": "AAA"}]})` (1 tab)
- Expected: `ValidationResult(status="error", messages=[{severity: "error", code: "MIN_ITEMS_VIOLATION", field: "data.tabs", min: 2, actual: 1}])`

**UT-6: Unknown Template Type**  
- Input: `validate("drag-and-drop", {})`
- Expected: raises `TemplateTypeNotFoundError` or returns error with code `TEMPLATE_TYPE_NOT_FOUND`

**UT-7: Schema Signature Computation Determinism**  
- Input: Two calls to `compute_signature({"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}})` with same schema
- Expected: Both calls return identical 64-char hex string

**UT-8: Fallback Contract Loading**  
- Input: Force `TemplateContractRepository.get_contract("tabs")` to fail (DB unavailable), then call `TemplateRegistry.get_contract("tabs")`
- Expected: Returns fallback contract with `schema_signature: "FALLBACK"` and correct minimal schema

### 6.2 Integration Test Scenarios

**IT-1: Tool Schema Registry Seeding**  
- Setup: Run the startup seed that populates `tool_schema_registry` from the predefined 12 tool definitions.
- Test: Query `SELECT tool_name FROM tool_schema_registry WHERE is_active = TRUE` and assert all 12 are present with correct `is_idempotent` flags.
- Expected: 12 rows, including `create_session(idempotent=false)`, `list_pages(idempotent=true)`, `validate_course(idempotent=true)`, etc.

**IT-2: Template Contract Migration from TemplateDefinitions**  
- Setup: Seed `template_definitions` table with 5 template entries using existing seed mechanism. Then run migration script that populates `template_contracts`.
- Test: Query `template_contracts` and assert 5 rows with matching `type_key` values. Each row has a non-null `schema_signature` of exactly 64 characters.
- Expected: 5 rows; each `json_schema` is valid JSON Schema draft-07.

**IT-3: Validation End-to-End with Session Auth**  
- Setup: Create valid session via `POST /api/v1/ai/sessions`. Then call `POST /api/v1/ai/tools/validate` with valid payload and invalid payload.
- Test: 
  1. Valid payload returns status 200 with `validation_status: "valid"`.
  2. Invalid payload (missing required field) returns status 200 with `validation_status: "error"` and error code `MISSING_REQUIRED_FIELD`.
  3. Unauthenticated request (no session header) returns status 401.
- Expected: All three assertions pass.

### 6.3 E2E / Acceptance Test Scenarios

**AT-1: Full AI Create Page Flow with Schema Validation**  
1. Create a course manually (via existing `POST /api/v1/courses`).
2. Start an AI session for that course (`POST /api/v1/ai/sessions`).
3. Call `list_pages` (returns empty, as expected).
4. Call `propose_create_page` with valid `tabs` data (2 tabs with title+content).
5. Assert response contains `validation_status: "valid"` and a `proposal_id`.
6. Call `apply_page_proposal` with `user_confirmed: true`.
7. Assert page is created (verify via `GET /api/v1/ai/tools/fetch_page` or `GET /api/v1/courses/{courseId}/pages`).
8. Assert audit log contains one `propose_create_page` and one `apply_page_proposal` entry.

**AT-2: Validation Error Recovery**  
1. Create course + start AI session.
2. Call `propose_create_page` with `final-assessment` data containing 1 question only.
3. Assert response `validation_status: "error"` and message references "at least 3 questions".
4. Call `propose_*` again with corrected data (3 questions).
5. Assert `validation_status: "valid"`.
6. Apply proposal. Assert page created.
7. Assert only one page created (no stray pages from failed attempt 3).
8. Assert validation error logged in audit trail.

### 6.4 Manual QA Verification Procedure

**Step 1: Verify Tool Schema Registry**
1. Connect to test database. Query `tool_schema_registry` table. Expect 12 rows with tool names matching `TOOL_SCHEMAS_CLAUDE_NATIVE.md`.
2. Verify each row has `input_schema_json` and `output_schema_json` as valid JSON.
3. Verify `is_idempotent` values match the document: `create_session=false`, `list_pages=true`, `fetch_page=true`, `propose_create_page=false`, `apply_page_proposal=true`, `propose_update_page=false`, `apply_update_proposal=true`, `propose_delete_page=false`, `confirm_delete_page=false`, `validate_course=true`, `query_similar_courses=true`, `analyze_document_for_import=false`.

**Step 2: Verify Template Contracts**
1. Hit `GET /api/v1/ai/templates` with a valid session header.
2. Verify response contains exactly 5 templates: `text-content`, `tabs`, `accordion`, `click-reveal`, `final-assessment`.
3. Verify each template has non-null `schema_signature` (64 hex chars).
4. Verify each template's `validation_rules` constraints match the spec (e.g., `tabs.min_items=2`, `tabs.max_items=6`).

**Step 3: Verify Validation Engine**
1. Open `/api/v1/ai/tools/validate` with a REST client or Swagger UI.
2. Test each template type with valid data -- expect `status: "valid"`.
3. Test each template type with boundary conditions:
   - `tabs` with 1 item -> error `MIN_ITEMS_VIOLATION`
   - `tabs` with 7 items -> error `MAX_ITEMS_VIOLATION`
   - `final-assessment` with passing_score=101 -> error `BUSINESS_RULE_VIOLATION`
   - `text-content` without `content` -> error `MISSING_REQUIRED_FIELD`
   - `accordion` with 21 items -> error `MAX_ITEMS_VIOLATION`
4. Test with invalid JSON -> expect 422 FastAPI validation error.

**Step 4: Verify Error Codes Catalog**
1. Read `config/error_codes.json` and verify all error codes listed in section 3.3 are present with descriptions and `retryable` flags.
2. Trigger each error code via the validation engine and verify the response `code` matches.

**Step 5: Verify Fallback Contracts**
1. Temporarily stop the database (or block access to the `template_contracts` table).
2. Hit `GET /api/v1/ai/templates` -- must still return 5 template contracts (with `schema_signature: "FALLBACK"`).
3. Verify validation engine still works (with reduced strictness).
4. Restore database access.
5. Hit same endpoint again -- must now return full contracts with real signatures.

---

## 7. DEFINITION OF DONE

All of the following checklist items must be completed and verified:

- [ ] **DD-1:** `tool_schema_registry` table created via Alembic migration with correct columns, indices, and UNIQUE constraint on `tool_name`.
- [ ] **DD-2:** `template_contracts` table created via Alembic migration with correct columns, indices, and unique index on active `type_key`.
- [ ] **DD-3:** `template_data_migrations` table created via Alembic migration with correct columns and indices.
- [ ] **DD-4:** `ToolSchemaRepository` implemented with methods: `get_tool`, `list_tools`, `register_tool`, `deregister_tool`, `upsert_tool`.
- [ ] **DD-5:** `ToolRegistry` implemented with `get_system_prompt_tools_block` returning only AI-facing tool definitions.
- [ ] **DD-6:** `TemplateContractRepository` implemented with methods: `get_contract`, `list_contracts`, `register_contract`, `deprecate_contract`.
- [ ] **DD-7:** `TemplateRegistry` implemented with `get_contract`, `list_contracts`, `get_schema_for_type`, `get_business_rules`, `compute_signature`, and fallback contract loading.
- [ ] **DD-8:** `TemplateValidationEngine` implemented with `validate`, `validate_schema`, `validate_business_rules` methods, covering all 5 template types.
- [ ] **DD-9:** `POST /api/v1/ai/tools/validate` endpoint implemented with proper auth, error handling, and response shape.
- [ ] **DD-10:** `GET /api/v1/ai/templates` and `GET /api/v1/ai/templates/{type_key}` endpoints implemented.
- [ ] **DD-11:** Startup seed updated to populate `tool_schema_registry` with 12 tool definitions from `TOOL_SCHEMAS_CLAUDE_NATIVE.md`.
- [ ] **DD-12:** Startup seed updated to populate `template_contracts` with 5 template contracts.
- [ ] **DD-13:** Fallback contract file `config/fallback_contracts.json` created and load-in-prod verified with DB unavailability test.
- [ ] **DD-14:** Error code catalog `config/error_codes.json` created with all codes from section 3.3.
- [ ] **DD-15:** Unit tests: at least 8 scenarios (all from section 6.1) passing with >= 90% coverage on new validation service code.
- [ ] **DD-16:** Integration tests: at least 3 scenarios (all from section 6.2) passing.
- [ ] **DD-17:** E2E tests: at least 2 scenarios (all from section 6.3) passing.
- [ ] **DD-18:** Manual QA: all 5 verification steps from section 6.4 completed and signed off.
- [ ] **DD-19:** Non-regression: existing `POST /api/v1/courses` and `POST /api/v1/courses/{courseId}/templates` endpoints return identical responses before and after this story.
- [ ] **DD-20:** Non-regression: existing SCORM export pipeline (which uses `template_definitions` table) produces identical output before and after this story.
- [ ] **DD-21:** Performance: schema validation for worst-case payload (50-question assessment) completes under 500ms p99.
- [ ] **DD-22:** All `is_active` and versioning fields correctly toggle; deactivated tools/contracts are excluded from API responses but not deleted.
- [ ] **DD-23:** `schema_signature` caching layer invalidates on contract update (TTL or event-based).
- [ ] **DD-24:** Data migration from `template_definitions` to `template_contracts` at startup is idempotent (safe to re-run).

---

## 8. TASKS & SUB-TASKS

| ID | Task Description | Owner Role | Est. (hrs) | Dependencies |
|---|---|---|---|---|
| **T1** | **Create database schema (migration + models)** | Backend Engineer | 6 | US-AI-003 complete (for AI module structure) |
| T1.1 | Create Alembic migration for `tool_schema_registry` table | Backend Engineer | 1 | None |
| T1.2 | Create Alembic migration for `template_contracts` table | Backend Engineer | 1 | None |
| T1.3 | Create Alembic migration for `template_data_migrations` table | Backend Engineer | 0.5 | None |
| T1.4 | Create Pydantic models: `ToolSchema`, `TemplateContract`, `ValidationResult`, `ValidationMessage` | Backend Engineer | 2 | None |
| T1.5 | Write data migration logic from `template_definitions` to `template_contracts` at startup | Backend Engineer | 1.5 | T1.2 |
| **T2** | **Build Tool Schema Registry** | Backend Engineer | 8 | T1 |
| T2.1 | Implement `ToolSchemaRepository` (CRUD, upsert) | Backend Engineer | 2 | T1.4 |
| T2.2 | Implement `ToolRegistry` service (`get_tool`, `list_tools`, `get_system_prompt_tools_block`) | Backend Engineer | 3 | T2.1 |
| T2.3 | Write startup seed: load 12 tool definitions from config into `tool_schema_registry` | Backend Engineer | 2 | T2.1 |
| T2.4 | Implement schema signature computation (SHA-256 over canonical JSON) | Backend Engineer | 1 | None |
| **T3** | **Build Template Contract Registry** | Backend Engineer | 10 | T1 |
| T3.1 | Implement `TemplateContractRepository` (CRUD, get_active, deprecate) | Backend Engineer | 2 | T1.4 |
| T3.2 | Implement `TemplateRegistry` service with in-memory LRU cache | Backend Engineer | 3 | T3.1 |
| T3.3 | Create fallback contracts JSON file (`config/fallback_contracts.json`) | Backend Engineer | 1 | None |
| T3.4 | Implement fallback loading logic in `TemplateRegistry` | Backend Engineer | 2 | T3.3 |
| T3.5 | Write startup seed: populate `template_contracts` with 5 contracts | Backend Engineer | 2 | T3.1 |
| **T4** | **Build Validation Engine** | Backend Engineer | 12 | T3 |
| T4.1 | Implement `TemplateValidationEngine` with JSON Schema validation (using `jsonschema` library) | Backend Engineer | 4 | T3.2 |
| T4.2 | Implement business rules per template type (min/max items, score ranges, field presence) | Backend Engineer | 4 | T4.1 |
| T4.3 | Implement `ValidationResult` builder with error code mapping | Backend Engineer | 2 | T4.1 |
| T4.4 | Implement sanitization layer (strip script tags, enforce length limits) | Backend Engineer | 2 | T4.1 |
| **T5** | **Implement API Endpoints** | Backend Engineer | 6 | T2, T4 |
| T5.1 | Create `app/routers/ai_templates.py` with `GET /api/v1/ai/templates` and `GET /api/v1/ai/templates/{type_key}` | Backend Engineer | 2 | T3.2 |
| T5.2 | Add `POST /api/v1/ai/tools/validate` endpoint (to existing or new AI tools router) | Backend Engineer | 2 | T4.3 |
| T5.3 | Integrate validation engine into `propose_create_page` and `propose_update_page` handlers (from US-AI-003) | Backend Engineer | 2 | T4.3, US-AI-003 |
| **T6** | **Create Error Code Catalog + Logging** | Backend Engineer | 4 | T4 |
| T6.1 | Create `config/error_codes.json` with all codes from spec | Backend Engineer | 1 | None |
| T6.2 | Implement audit logging for tool calls (input hash, validation result, duration) | Backend Engineer | 2 | T5.2 |
| T6.3 | Implement rate limiting for validation endpoint (configurable, default 100/hour) | Backend Engineer | 1 | T5.2 |
| **T7** | **Testing & QA** | QA Engineer | 10 | T2-T6 |
| T7.1 | Write unit tests for `ToolRegistry` (3 scenarios) | QA Engineer | 2 | T2 |
| T7.2 | Write unit tests for `TemplateRegistry` (3 scenarios including fallback) | QA Engineer | 2 | T3 |
| T7.3 | Write unit tests for `ValidationEngine` (8 scenarios from section 6.1) | QA Engineer | 3 | T4 |
| T7.4 | Write integration tests (3 scenarios from section 6.2) | QA Engineer | 2 | T5 |
| T7.5 | Write E2E tests (2 scenarios from section 6.3) | QA Engineer | 3 | T5 |
| T7.6 | Execute manual QA verification (5 steps from section 6.4) | QA Engineer | 3 | T5 |
| **T8** | **Documentation** | Technical Writer | 4 | T5 |
| T8.1 | Update `TOOL_SCHEMAS_CLAUDE_NATIVE.md` with versioning details and error codes | Technical Writer | 2 | T6.1 |
| T8.2 | Write API docs for new endpoints (auto-generated by FastAPI) | Technical Writer | 1 | T5 |
| T8.3 | Write developer guide for adding a new template contract | Technical Writer | 1 | T3 |

**Total Estimated Effort:** 60 hours (approximately 7.5 engineering days)

**Critical Path:** T1 -> T3 -> T4 -> T5 -> T7 (validation engine is on the critical path because it blocks the propose/apply tool feature from US-AI-003). T2 can be done in parallel with T3. T6 can be done in parallel with T5. T8 can be done in parallel with T7.

---