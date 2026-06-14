# US-AI-044 — Two-Tier Model Architecture: Planner and Generator Separation

---

## Section 1 — Title and Metadata

| Field | Value |
|---|---|
| **User Story ID** | US-AI-044 |
| **Title** | Two-Tier Model Architecture: Planner and Generator Separation |
| **Source Flow** | Create Page Proposal and Apply Flow - Platform Runtime and Operations1.1.mmd (Phase 3 — Core AI Pipeline); Create Page Proposal and Apply Flow1.0.mmd (Phase 4 — Generation and Pruning) |
| **Audit Gap** | RESEARCH_AUDIT.md GAP-7: "Planner Model vs Generator Model Separation — The architecture describes two tiers of AI models: a fast/cheap 'Planner' that determines structure and template selection, and a premium 'Generator' that produces schema-bound content." |
| **Priority** | SHOULD |
| **Depends On** | US-AI-026 (Multi-Provider Model Routing and Fallback) |
| **Unlocks** | US-AI-028 (Context Pruning and Token Optimization), US-AI-029 (Batch Proposal Operations), US-AI-036 (Cost Tracking and Token Budget Enforcement) |
| **Status** | DRAFT |
| **Author** | Technical Product Owner |

---

## Section 2 — Functional Specification

### 2.1 User Story

> **As an Operator**, I want the AI authoring system to use a fast, cheap model for structural planning decisions (template selection, page ordering, content outline) and a premium, capable model for schema-bound content generation, so that token costs are minimized for routine cognitive work while quality is maximized for the final content output that end-learners see.

### 2.2 Functional Requirements

The following 11 numbered requirements define the complete scope of this story.

**FR-PLAN-01 (Planner Model Tier Definition):** The system MUST define a distinct planner model tier configured via environment variable `AI_PLANNER_MODEL`. The planner tier is used exclusively for structural and decision-making tasks: analyzing page structure, selecting template types, determining content ordering, and producing high-level outlines. The planner model MUST be a fast, low-cost model class (e.g., GPT-4o-mini, Claude 3 Haiku) with a target p50 latency under 1.5 seconds per call and a per-token cost no greater than 20% of the generator tier model cost.

**FR-PLAN-02 (Generator Model Tier Definition):** The system MUST define a distinct generator model tier configured via environment variable `AI_GENERATOR_MODEL`. The generator tier is used exclusively for schema-bound content production tasks: generating full template data payloads (text content, accordion panels, tab items, click-to-reveal interactions, assessment questions and scoring configuration), producing course metadata, and composing final validation-ready content. The generator model MUST be a premium, high-capability model class (e.g., GPT-4o, Claude 3.5 Sonnet) with a target p50 latency under 5 seconds per call and structured output / tool-calling support.

**FR-PLAN-03 (Task-to-Tier Routing Matrix):** The system MUST route every AI operation to a model tier according to a configuration-driven task-to-tier routing matrix. The matrix defines, for each task type, which model tier handles it. Task types include: `template_selection`, `page_ordering`, `content_outline`, `page_content_generation`, `batch_content_generation`, `course_metadata_generation`, `segment_document`, `refine_content`, `clarify_ambiguity`, `reply_conversational`. The routing matrix is stored as a JSON configuration file (`config/ai_tier_routing.json`) and is reloadable at runtime without server restart.

**FR-PLAN-04 (Planner Output Contract):** The planner model MUST produce a structured, schema-enforced output that the downstream generator consumes. The planner output schema includes: selected `templateType` (enum of allowed templates), a `contentBrief` (string, max 2000 characters describing what content the generator should produce), a `structureHint` (optional JSON object providing structural guidance such as number of accordion panels, number of tab items, question count range for assessments), and `sourceMaterial` (optional array of excerpts or references from the session context). The planner output MUST be validated against the planner output JSON schema before being passed to the generator.

**FR-PLAN-05 (Generator Input Contract):** The generator model MUST receive the planner's validated output as part of its system prompt context. The generator's system prompt MUST include: the validated `templateType`, the `contentBrief` as the primary content directive, the `structureHint` if present, the `sourceMaterial` if present, and the full template JSON schema for the selected template type. The generator MUST NOT be asked to re-decide the template type or structural decisions — those are the planner's domain and are treated as ground truth for the generation phase.

**FR-PLAN-06 (Atomic Checkpoint Between Planner and Generator):** After the planner produces output and before the generator begins, the system MUST write an atomic checkpoint to the `ai_generation_checkpoints` table. The checkpoint record includes: `session_id`, `proposal_id`, `phase` (enum: `planning_complete`), `planner_model_id`, `planner_input_tokens`, `planner_output_tokens`, `planner_latency_ms`, `planner_output` (the validated output JSON), `context_snapshot` (a hash of the system prompt context used), and `created_at`. This checkpoint enables recovery: if the generation phase crashes, the workflow can resume from the planning checkpoint without re-invoking the planner.

**FR-PLAN-07 (Generator Retry Without Planner Re-Execution):** If the generator's output fails schema validation or business rule validation, the system MUST retry generation using the existing planner output without re-invoking the planner model. The number of allowed generator retries is configured via `AI_GENERATOR_MAX_RETRIES` (default 2). Each retry must include the validation error messages in the generator's context so the model can correct specific field errors. Re-invoking the planner is only permitted if the planner checkpoint has expired or if the user changes the structural requirements.

**FR-PLAN-08 (Fallback Between Tiers):** If the planner model fails (timeout, rate limit, server error), the system MUST apply the US-AI-026 multi-provider fallback logic within the planner tier: try the configured fallback planner model (same tier, different provider). If all planner-tier providers fail, the system may optionally fall back to the generator-tier model as a last-resort planner with a logged warning and telemetry event. Conversely, if the generator model fails and all generator-tier fallbacks are exhausted, the system MUST NOT fall back to the planner tier for content generation — the operation is marked as failed because the planner tier lacks the capability to produce schema-bound content.

**FR-PLAN-09 (Tier-Specific Prompt Templates):** The system MUST maintain separate versioned system prompt templates for the planner tier and the generator tier. The planner prompt instructs the model to focus on structure, organization, and template selection without producing full content. The generator prompt includes the planner output and instructs the model to produce fully populated, schema-compliant content. Both prompt templates are stored in `ai_prompt_versions` (US-AI-042) with a `model_tier` discriminator column. The planner prompt MUST be significantly shorter than the generator prompt (target: planner prompt under 800 tokens, generator prompt under 3000 tokens excluding planner output injection).

**FR-PLAN-10 (Cost Attribution Per Tier):** Every AI model invocation MUST record the model tier (`planner`, `generator`, `repair`, `safety`) in the telemetry and audit records. The cost tracking system (US-AI-036) MUST attribute token usage and computed cost separately per tier, enabling operators to see: planner-to-generator cost ratio, average planner cost per session, average generator cost per session, and tier-specific budget enforcement (e.g., cap planner spending at 30% of total session budget).

**FR-PLAN-11 (Tier Performance Telemetry):** The system MUST emit the following tier-specific metrics for every generation workflow: `planner_latency_ms`, `planner_token_count_total` (input + output), `planner_model_id`, `generator_latency_ms`, `generator_token_count_total`, `generator_model_id`, `planner_to_generator_ratio` (generator tokens / planner tokens), `generator_retry_count`, `planner_success`, `generator_success`, and `workflow_total_latency_ms`. These metrics MUST be available in the observability dashboard (US-AI-021) grouped by workflow type, template type, and tenant.

### 2.3 User Flow

#### Happy Path: Single Page Creation

```
Step 1: User sends instruction via chat: "Create an introductory module about data science with a text overview and a comparison of tools."
Step 2: AI Orchestrator (US-AI-023) invokes the planner model (fast/cheap tier) with a planning-specific system prompt.
Step 3: Planner model analyzes the request and produces structured output:
        - page 1: templateType="text-content", contentBrief="Introduction to data science covering definition and importance", structureHint=null
        - page 2: templateType="tabs", contentBrief="Comparison of Python, R, and SQL for data science", structureHint={"minTabs":3, "maxTabs":5}
Step 4: Planner output is validated against the planner output schema. Checkpoint is written to ai_generation_checkpoints.
Step 5: Context Pruning Engine (US-AI-028) uses the planner output to prune unused template schemas from the generator context.
Step 6: For each page, the orchestrator invokes the generator model (premium tier) with: planner output, template JSON schema, pruned context, and generation-specific system prompt.
Step 7: Generator produces full template-compliant data payloads for each page.
Step 8: Generator output passes schema validation and business rule validation.
Step 9: Proposals are created (US-AI-009) and presented to the user for review.
Step 10: User approves; proposals are applied (US-AI-010).
```

#### Error Path 1: Generator Output Fails Validation

```
Step 1-6: Same as happy path.
Step 7: Generator produces data for a "tabs" page with only 1 tab item (violates minimum 2-tab business rule).
Step 8: Validation returns error: "Tabs template requires at least 2 items; received 1."
Step 9: Orchestrator invokes generator retry (retry 1 of 2) with the same planner output PLUS the validation error message.
Step 10: Generator produces corrected data with 3 tab items.
Step 11: Validation passes. Proposals created. User reviews and approves.
```

#### Error Path 2: Planner Model Timeout

```
Step 1: User sends instruction.
Step 2: Orchestrator invokes planner model. Planner model times out after configured timeout (default 15 seconds).
Step 3: Orchestrator applies US-AI-026 fallback: retries with configured fallback planner model (same tier, different provider).
Step 4: Fallback planner succeeds. Planner output validated. Checkpoint written.
Step 5-10: Continue with generator as in happy path.
```

#### Error Path 3: Planner and All Planner Fallbacks Fail

```
Step 1-2: Planner model times out.
Step 3: Fallback planner model also times out.
Step 4: Orchestrator logs warning and optionally invokes generator-tier model as last-resort planner (feature-flagged).
Step 5: If last-resort planner succeeds, operation continues with a telemetry event marking "fallback_planner_used_generator_tier".
Step 6: If last-resort planner also fails, operation returns error to user: "AI service temporarily unavailable for content planning. Please try again."
```

### 2.4 UI/UX Requirements

1. **Tier-Indicator Badge (Admin Dashboard):** The admin audit and telemetry UI (US-AI-020, US-AI-021) MUST display per-operation model tier usage as a colored badge: blue for "Planner", green for "Generator", yellow for "Repair", gray for "Safety". Each badge shows the model ID on hover.

2. **Cost-Breakdown Widget:** The cost tracking UI (US-AI-036) MUST display a tier-based cost breakdown pie chart showing the proportion of total cost attributed to each model tier. The widget MUST include a toggle to show planner-to-generator cost ratio.

3. **Advanced Mode Toggle (Developer Settings):** An optional advanced settings toggle (visible to admins only) allows overriding the tier routing for individual sessions: "Force Planner Model" overrides the planner model for all operations; "Force Generator Model" uses the generator for both planning and generation; "Auto (Default)" uses the configured tier routing matrix.

4. **No End-User Visible Difference:** The end user (author using the AI chat panel) MUST NOT see any indication of the two-tier architecture in the standard flow. All tier routing, model fallback, and checkpoint logic happens transparently in the backend. The user interacts with the AI chat as a single unified experience.

---

## Section 3 — Technical Specification

### 3.1 API Contracts

#### 3.1.1 Planner Service Internal API

The planner service is an internal service (not directly exposed as an HTTP endpoint) called by the AI chat orchestrator.

```python
# app/services/ai/planner_service.py

class PlannerInput(BaseModel):
    session_id: str
    proposal_id: Optional[str] = None  # Set if regenerating for an existing proposal
    user_prompt: str
    course_context: CourseContext  # Current course state summary
    available_templates: list[str]  # Whitelist from session config
    rag_results: Optional[list[RagResult]] = None
    system_prompt_version: str

class PlannerOutput(BaseModel):
    templateType: str  # Must be in allowed templates enum
    contentBrief: str  # Max 2000 characters
    structureHint: Optional[dict] = None
    sourceMaterial: Optional[list[str]] = None
    confidenceScore: Optional[float] = Field(None, ge=0.0, le=1.0)

class PlannerResponse(BaseModel):
    planner_output: PlannerOutput
    model_id: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    fallback_occurred: bool = False
    last_resort_generator_tier_used: bool = False
```

#### 3.1.2 Generator Service Internal API

```python
# app/services/ai/generator_service.py

class GeneratorInput(BaseModel):
    session_id: str
    proposal_id: Optional[str] = None
    planner_output: PlannerOutput  # Validated output from planner
    template_schema: dict  # Full JSON schema for the selected template type
    pruned_context: dict  # Context after pruning (US-AI-028)
    validation_errors: Optional[list[ValidationError]] = None  # For retries
    retry_number: int = 0
    system_prompt_version: str

class GeneratorResponse(BaseModel):
    template_data: dict  # Schema-validated template data
    model_id: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    fallback_occurred: bool = False
    raw_output: Optional[str] = None  # Raw LLM output before parsing (for audit)
    json_repair_events: Optional[list[JsonRepairEvent]] = None  # From US-AI-027
```

#### 3.1.3 Tier Assignment and Orchestration

```python
# app/services/ai/tier_orchestrator.py

class TierRoutingRule(BaseModel):
    task_type: str
    tier: Literal["planner", "generator", "repair", "safety"]
    model_override: Optional[str] = None  # Optional per-rule model ID override
    allow_fallback: bool = True
    allow_last_resort_generator: bool = False  # Only for planner tier

class TierRoutingConfig(BaseModel):
    rules: list[TierRoutingRule]
    default_tier: str = "generator"
    planner_timeout_seconds: int = 15
    generator_timeout_seconds: int = 60

class WorkflowMetrics(BaseModel):
    planner_latency_ms: Optional[int] = None
    planner_token_input: Optional[int] = None
    planner_token_output: Optional[int] = None
    planner_model_id: Optional[str] = None
    planner_retries: int = 0
    planner_success: bool = False
    generator_latency_ms: Optional[int] = None
    generator_token_input: Optional[int] = None
    generator_token_output: Optional[int] = None
    generator_model_id: Optional[str] = None
    generator_retries: int = 0
    generator_success: bool = False
    total_latency_ms: Optional[int] = None
    planner_to_generator_token_ratio: Optional[float] = None
    fallback_used: bool = False
    last_resort_generator_used: bool = False
```

#### 3.1.4 Orchestrator Flow Pseudocode

```python
async def generate_page_content(
    session_id: str,
    proposal_id: str,
    user_prompt: str,
    course_context: CourseContext,
    tier_config: TierRoutingConfig,
    available_templates: list[str]
) -> GeneratorResponse:
    """
    Two-tier generation flow: planner -> checkpoint -> generator.
    """
    # Phase 1: Planning
    planner_input = PlannerInput(
        session_id=session_id,
        proposal_id=proposal_id,
        user_prompt=user_prompt,
        course_context=course_context,
        available_templates=available_templates
    )
    
    planner_response = None
    planner_last_error = None
    
    for attempt in range(1 + len(tier_config.rules)):  # Primary + fallbacks
        try:
            planner_response = await invoke_planner_with_timeout(
                planner_input,
                model_tier="planner",
                timeout_seconds=tier_config.planner_timeout_seconds
            )
            # Validate planner output
            validate_planner_output(planner_response.planner_output, available_templates)
            planner_response.planner_success = True
            break
        except TimeoutError as e:
            planner_last_error = e
            # Apply US-AI-026 fallback logic
            planner_response = await attempt_planner_fallback(attempt, planner_input, tier_config)
            if planner_response and planner_response.planner_output:
                planner_response.fallback_occurred = True
                break
        except ValidationError as e:
            planner_last_error = e
            continue
    
    if not planner_response or not planner_response.planner_output:
        # Last resort: try generator tier as planner
        if tier_config.allow_last_resort_planner_fallback:
            planner_response = await invoke_planner_with_timeout(
                planner_input,
                model_tier="generator",
                timeout_seconds=tier_config.generator_timeout_seconds
            )
            if planner_response and planner_response.planner_output:
                planner_response.last_resort_generator_tier_used = True
            else:
                raise AIServiceUnavailable("Both planner and generator tiers failed for planning")
        else:
            raise AIServiceUnavailable("All planner-tier models failed and generator fallback disabled")
    
    # Phase 2: Atomic Checkpoint Write
    await write_planner_checkpoint(
        session_id=session_id,
        proposal_id=proposal_id,
        planner_output=planner_response.planner_output,
        model_id=planner_response.model_id,
        input_tokens=planner_response.input_tokens,
        output_tokens=planner_response.output_tokens,
        latency_ms=planner_response.latency_ms,
        fallback_occurred=planner_response.fallback_occurred
    )
    
    # Phase 3: Context Pruning (delegated to US-AI-028)
    pruned_context = await prune_context_for_generator(
        planner_output=planner_response.planner_output,
        course_context=course_context,
        available_templates=available_templates
    )
    
    # Phase 4: Generation
    generator_input = GeneratorInput(
        session_id=session_id,
        proposal_id=proposal_id,
        planner_output=planner_response.planner_output,
        template_schema=get_template_schema(planner_response.planner_output.templateType),
        pruned_context=pruned_context
    )
    
    generator_response = None
    for attempt in range(1 + AI_GENERATOR_MAX_RETRIES):
        try:
            generator_response = await invoke_generator_with_timeout(
                generator_input,
                model_tier="generator",
                retry_number=attempt,
                timeout_seconds=tier_config.generator_timeout_seconds
            )
            # Validate generator output against template schema
            validation_result = validate_generator_output(
                generator_response.template_data,
                planner_response.planner_output.templateType
            )
            if validation_result.status == "valid":
                generator_response.generator_success = True
                break
            else:
                # Feed validation errors back for retry
                generator_input.validation_errors = validation_result.errors
                generator_input.retry_number = attempt + 1
        except Exception as e:
            generator_response = await attempt_generator_fallback(attempt, generator_input, tier_config)
            if generator_response and generator_response.template_data:
                generator_response.fallback_occurred = True
                break
    
    if not generator_response or not generator_response.template_data:
        raise AIGenerationFailed(
            f"Generator failed after {AI_GENERATOR_MAX_RETRIES + 1} attempts"
        )
    
    # Phase 5: Emit Workflow Metrics
    workflow_metrics = build_workflow_metrics(
        planner_response, generator_response
    )
    await emit_workflow_telemetry(workflow_metrics)
    
    return generator_response
```

### 3.2 Database Schema

#### 3.2.1 `ai_generation_checkpoints` Table

```sql
CREATE TABLE IF NOT EXISTS ai_generation_checkpoints (
    id                      BIGSERIAL PRIMARY KEY,
    checkpoint_id           VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    
    -- Session and proposal linkage
    session_id              VARCHAR(64) NOT NULL,
    proposal_id             VARCHAR(64) NOT NULL,
    
    -- Phase tracking
    phase                   VARCHAR(32) NOT NULL CHECK (phase IN (
                                'planning_complete',
                                'generation_complete',
                                'validation_complete',
                                'failed'
                            )),
    
    -- Planner metadata
    planner_model_id        VARCHAR(128) NOT NULL,
    planner_provider        VARCHAR(64) NOT NULL,
    planner_input_tokens    INTEGER NOT NULL CHECK (planner_input_tokens >= 0),
    planner_output_tokens   INTEGER NOT NULL CHECK (planner_output_tokens >= 0),
    planner_latency_ms      INTEGER NOT NULL CHECK (planner_latency_ms >= 0),
    planner_fallback_used   BOOLEAN NOT NULL DEFAULT FALSE,
    planner_last_resort     BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Planner output (the validated decision data)
    planner_output          JSONB NOT NULL,
    
    -- Generator metadata (populated after generation phase)
    generator_model_id      VARCHAR(128),
    generator_provider      VARCHAR(64),
    generator_input_tokens  INTEGER CHECK (generator_input_tokens >= 0),
    generator_output_tokens INTEGER CHECK (generator_output_tokens >= 0),
    generator_latency_ms    INTEGER CHECK (generator_latency_ms >= 0),
    generator_retry_count   SMALLINT NOT NULL DEFAULT 0,
    generator_fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Context snapshot hash for replay debugging
    context_snapshot_hash   VARCHAR(64),  -- SHA-256 of serialized context
    
    -- Timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at            TIMESTAMPTZ,
    
    -- Foreign keys
    FOREIGN KEY (session_id) REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (proposal_id) REFERENCES ai_proposals(proposal_id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX idx_checkpoints_session ON ai_generation_checkpoints(session_id);
CREATE INDEX idx_checkpoints_proposal ON ai_generation_checkpoints(proposal_id);
CREATE INDEX idx_checkpoints_phase ON ai_generation_checkpoints(phase);
CREATE INDEX idx_checkpoints_created ON ai_generation_checkpoints(created_at);
CREATE UNIQUE INDEX idx_checkpoints_proposal_phase ON ai_generation_checkpoints(proposal_id, phase)
    WHERE phase = 'planning_complete';
```

#### 3.2.2 `ai_tier_routing_config` Table

```sql
CREATE TABLE IF NOT EXISTS ai_tier_routing_config (
    id                      BIGSERIAL PRIMARY KEY,
    
    -- Task type and tier assignment
    task_type               VARCHAR(64) NOT NULL UNIQUE CHECK (task_type IN (
                                'template_selection',
                                'page_ordering',
                                'content_outline',
                                'page_content_generation',
                                'batch_content_generation',
                                'course_metadata_generation',
                                'segment_document',
                                'refine_content',
                                'clarify_ambiguity',
                                'reply_conversational'
                            )),
    assigned_tier           VARCHAR(16) NOT NULL CHECK (assigned_tier IN (
                                'planner', 'generator', 'repair', 'safety'
                            )),
    
    -- Optional per-rule model override
    model_override          VARCHAR(128),
    allow_fallback          BOOLEAN NOT NULL DEFAULT TRUE,
    allow_last_resort       BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Metadata
    enabled                 BOOLEAN NOT NULL DEFAULT TRUE,
    description             TEXT,
    updated_by              VARCHAR(128) NOT NULL DEFAULT 'system',
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version                 INTEGER NOT NULL DEFAULT 1
);

-- Seed default routing rules
INSERT INTO ai_tier_routing_config (task_type, assigned_tier, description) VALUES
    ('template_selection',      'planner',   'Select appropriate template type based on user intent and content'),
    ('page_ordering',           'planner',   'Determine page sequence and ordering within a course'),
    ('content_outline',         'planner',   'Produce high-level content outline and structure'),
    ('page_content_generation', 'generator', 'Generate full template-compliant content data for a single page'),
    ('batch_content_generation','generator', 'Generate content for multiple pages in batch'),
    ('course_metadata_generation','generator','Generate course title, description, learning objectives'),
    ('segment_document',        'planner',   'Map extracted document sections to suggested templates'),
    ('refine_content',          'generator', 'Refine or regenerate existing page content based on user feedback'),
    ('clarify_ambiguity',       'planner',   'Resolve ambiguous user requests by asking clarifying questions'),
    ('reply_conversational',    'planner',   'General conversational replies that do not require content generation');
```

#### 3.2.3 Extension to `ai_sessions` Table (New Columns)

```sql
-- Add tier override columns to ai_sessions
ALTER TABLE ai_sessions
    ADD COLUMN IF NOT EXISTS tier_override VARCHAR(16) CHECK (
        tier_override IN ('auto', 'force_planner', 'force_generator', 'force_repair')
    ) DEFAULT 'auto',
    ADD COLUMN IF NOT EXISTS planner_cost_accumulated NUMERIC(12,6) NOT NULL DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS generator_cost_accumulated NUMERIC(12,6) NOT NULL DEFAULT 0.0;
```

#### 3.2.4 Extension to `ai_audit_logs` Table (New Columns)

```sql
-- Add tier tracking columns to ai_audit_logs (see US-AI-020 for base schema)
ALTER TABLE ai_audit_logs
    ADD COLUMN IF NOT EXISTS model_tier VARCHAR(16) CHECK (
        model_tier IN ('planner', 'generator', 'repair', 'safety')
    ),
    ADD COLUMN IF NOT EXISTS planner_output_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS generation_checkpoint_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS tier_fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS tier_fallback_reason TEXT;
```

### 3.3 Service/Module Design

#### Module Tree

```
app/services/ai/
    __init__.py
    model_router.py                  # US-AI-026: Multi-provider routing (extended)
    tier_orchestrator.py             # NEW: Two-tier workflow orchestration
    planner_service.py               # NEW: Planner model invocation and output validation
    generator_service.py             # NEW: Generator model invocation and retry logic
    checkpoint_service.py            # NEW: Atomic checkpoint read/write for generation phases
    tier_routing_config.py           # NEW: Configuration loader for tier routing matrix
    context_pruner.py                # US-AI-028: Context pruning (consumes planner output)
    json_repair.py                   # US-AI-027: JSON repair pipeline
    prompt_manager.py                # US-AI-042: Versioned prompt management
    cost_tracker.py                  # US-AI-036: Cost tracking (extended for tier attribution)
    ...
```

#### `tier_orchestrator.py` Responsibilities

1. Accept generation request from the AI chat orchestrator (US-AI-023).
2. Resolve the task type to a model tier using `TierRoutingConfig`.
3. For planner-tier tasks: invoke `PlannerService`, handle timeouts and fallbacks, validate planner output.
4. Write atomic checkpoint after planner success.
5. For generator-tier tasks: invoke `GeneratorService`, pass planner output + template schema + pruned context.
6. Handle generator retries on validation failure.
7. Emit workflow-level telemetry metrics.
8. Route last-resort planner fallback to generator tier if configured.

#### `planner_service.py` Responsibilities

1. Build the planner system prompt from the tier-specific prompt template.
2. Invoke the model router (US-AI-026) targeting the planner tier.
3. Parse and validate the planner's structured output against the planner output schema.
4. Return `PlannerResponse` with full telemetry data.
5. Handle planner-specific error scenarios (empty output, invalid template type, malformed JSON).

#### `generator_service.py` Responsibilities

1. Build the generator system prompt: inject planner output, template schema, pruned context, content brief.
2. Invoke the model router (US-AI-026) targeting the generator tier.
3. Parse the generator's output and validate against the target template JSON schema.
4. On validation failure: append validation errors to the retry context and re-invoke the generator.
5. On JSON parse failure: delegate to US-AI-027 JSON repair pipeline before retrying generator.
6. Return `GeneratorResponse` with full telemetry data.

#### `checkpoint_service.py` Responsibilities

1. `write_planner_checkpoint()`: Write a new row to `ai_generation_checkpoints` with phase=`planning_complete`. If a checkpoint for this `(proposal_id, 'planning_complete')` already exists, return the existing checkpoint (idempotent).
2. `write_generator_checkpoint()`: Update the existing planning checkpoint row with generator metadata and phase=`generation_complete`.
3. `get_planner_checkpoint(proposal_id)`: Retrieve the most recent planning checkpoint for a proposal. Used during recovery.
4. `expire_checkpoints(session_id)`: Mark all incomplete checkpoints for a session as phase=`failed` when a session ends or errors out.

#### `tier_routing_config.py` Responsibilities

1. Load `ai_tier_routing_config` table into a cached `TierRoutingConfig` object at startup.
2. Provide a `get_tier_for_task(task_type: str) -> str` method that returns the assigned tier.
3. Support runtime reload via `reload_config()` without server restart (triggered by a configuration change event or admin API call).
4. Validate that all stored rules reference valid task types and tier values.
5. Emit a metric when the configuration is reloaded, recording the new version number.

### 3.4 Configuration Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `AI_PLANNER_MODEL` | str | `"claude-3-haiku-20240307"` | Model ID for the planner tier. Must be routable via US-AI-026. Must be a fast/cheap model class. |
| `AI_PLANNER_FALLBACK_MODEL` | str | `"gpt-4o-mini"` | Fallback model ID for the planner tier when primary planner model fails. |
| `AI_PLANNER_TIMEOUT_SECONDS` | int | `15` | Timeout in seconds for planner model invocations. |
| `AI_GENERATOR_MODEL` | str | `"claude-3-5-sonnet-20241022"` | Model ID for the generator tier. Must be a premium model with tool-calling and structured output support. |
| `AI_GENERATOR_FALLBACK_MODEL` | str | `"gpt-4o"` | Fallback model ID for the generator tier when primary generator model fails. |
| `AI_GENERATOR_TIMEOUT_SECONDS` | int | `60` | Timeout in seconds for generator model invocations. |
| `AI_GENERATOR_MAX_RETRIES` | int | `2` | Maximum number of generator retry attempts after validation failure, using the same planner output. |
| `AI_ALLOW_LAST_RESORT_PLANNER` | bool | `false` | If true, use the generator-tier model as a last-resort planner when all planner-tier models fail. |
| `AI_TIER_OVERRIDE` | str | `"auto"` | Global tier override. Values: `auto`, `force_planner`, `force_generator`. Can be overridden per session. |
| `AI_PLANNER_MAX_TOKENS` | int | `1024` | Max output tokens for planner model invocations. |
| `AI_GENERATOR_MAX_TOKENS` | int | `4096` | Max output tokens for generator model invocations. |
| `AI_PLANNER_TEMPERATURE` | float | `0.3` | Temperature for planner model (lower = more deterministic for structural decisions). |
| `AI_GENERATOR_TEMPERATURE` | float | `0.7` | Temperature for generator model (slightly higher for creative content generation). |
| `AI_CHECKPOINT_EXPIRY_HOURS` | int | `24` | Hours after which an incomplete checkpoint is considered expired and can be cleaned up. |
| `AI_TIER_ROUTING_CONFIG_PATH` | str | `"config/ai_tier_routing.json"` | File path for the JSON tier routing matrix configuration. |

### 3.5 Integration Points

| Integration | Direction | Description |
|---|---|---|
| US-AI-023 (AI Chat Endpoint) | Consumes | The chat orchestrator calls `TierOrchestrator.generate_page_content()` instead of directly calling the model router for content generation tasks. |
| US-AI-026 (Model Router) | Extends | The existing model router gains a `model_tier` parameter. Fallback logic is tier-aware: planner models fall back to other planner-tier providers; generator models fall back to other generator-tier providers. |
| US-AI-028 (Context Pruner) | Consumes | The context pruner receives the validated planner output and uses the `templateType` and `contentBrief` to prune unused template schemas from the generator context. |
| US-AI-027 (JSON Repair) | Consumes | When generator output fails JSON parsing, the repair pipeline is invoked. The repair tier is tracked separately in telemetry. |
| US-AI-036 (Cost Tracker) | Extends | Cost tracking is augmented with tier attribution. Each usage record includes `model_tier` column. Budget caps can be set per tier. |
| US-AI-042 (Prompt Versioning) | Extends | Prompt versions gain a `model_tier` discriminator. Planner and generator prompts are versioned independently. |
| US-AI-020 (Admin Audit) | Extends | Audit records include `model_tier`, `planner_output_snapshot`, and `generation_checkpoint_id`. |
| US-AI-021 (Observability) | Extends | Telemetry metrics include tier-specific latency, token counts, and success/failure rates. |
| US-AI-009 (Proposal Lifecycle) | Consumes | Proposal records reference the checkpoint ID so the full generation workflow can be traced. |

---

## Section 4 — Non-Functional Requirements

### 4.1 Performance Targets

| Metric | Target | Measurement Method |
|---|---|---|
| Planner model p50 latency | < 1.5 seconds | Histogram metric `ai_planner_latency_ms` |
| Planner model p95 latency | < 5 seconds | Histogram metric `ai_planner_latency_ms` |
| Generator model p50 latency | < 5 seconds | Histogram metric `ai_generator_latency_ms` |
| Generator model p95 latency | < 15 seconds | Histogram metric `ai_generator_latency_ms` |
| Checkpoint write latency | < 50 ms p99 | Timer metric `ai_checkpoint_write_ms` |
| Planner-to-generator context handoff latency | < 100 ms | Timer metric `ai_tier_handoff_ms` |
| Generator retry overhead (per retry) | < +60% of original call | Derived from `generator_retry_count` and `generator_latency_ms` |
| Planner cost per call | <= 20% of generator cost per call | Derived from `planner_output_tokens * planner_token_cost` vs `generator_output_tokens * generator_token_cost` |

### 4.2 Security Requirements

1. **Tier Isolation:** The model tier routing configuration MUST be validated server-side. Client-side tier override requests (e.g., from the advanced settings UI) MUST be validated against the user's role and tenant policy before being applied. Only users with the `ai_admin` role may set tier overrides.

2. **Prompt Injection Across Tiers:** The planner output injected into the generator's system prompt MUST be treated as untrusted data. It MUST be wrapped in a strict output boundary marker (e.g., `<!-- PLANNER_OUTPUT_START --> ... <!-- PLANNER_OUTPUT_END -->`) with clear instructions to the generator that the planner output is data, not instructions. The planner output MUST NOT be concatenated into the generator instruction section of the system prompt.

3. **Audit Completeness:** Every tier routing decision MUST be recorded in the audit log with enough context to reconstruct why a particular model was selected. This includes: task type, assigned tier, model ID actually used, fallback indicator, fallback reason code, and timestamp.

4. **Configuration Integrity:** The `ai_tier_routing_config` table and the `config/ai_tier_routing.json` file MUST be checksummed and validated at load time. Invalid configurations (missing rules, referencing non-existent task types, referencing non-existent model IDs) MUST cause the application to fail at startup rather than silently defaulting.

### 4.3 Reliability Requirements

1. **Planner Checkpoint Durability:** The checkpoint write after planner success MUST be completed before the generator phase begins. If the checkpoint write fails, the generator phase MUST NOT proceed. The planner output is considered uncommitted until the checkpoint is durable.

2. **Generator Retry Budget Exhaustion:** After exhausting `AI_GENERATOR_MAX_RETRIES` without producing valid output, the orchestrator MUST mark the proposal as `FAILED` in the proposal state machine (US-AI-009) with a failure reason of `generation_failed_after_retries`. The existing planner checkpoint remains valid for retry if the user requests regeneration.

3. **Crash Recovery:** If the orchestrator process crashes between the planner checkpoint write and generator success, a recovery process MUST detect the incomplete checkpoint (phase=`planning_complete`, `completed_at` IS NULL) and resume from the checkpoint data. The recovery MUST NOT re-invoke the planner.

4. **Tier Override Coherence:** If a session is created with `tier_override=force_planner`, the generator phase is skipped entirely and the planner output IS the content (for debugging/testing). If `tier_override=force_generator`, the planner phase is skipped and the generator handles both structural decisions and content generation using a combined system prompt.

### 4.4 Scalability Requirements

1. **Concurrent Planner Invocations:** The planner service MUST support at least 50 concurrent planner invocations per tenant without degradation. Planner invocations are primarily I/O-bound (API calls to LLM providers) and should use async I/O throughout.

2. **Checkpoint Table Growth:** The `ai_generation_checkpoints` table is expected to grow linearly with AI generation requests. A cleanup job (running daily) MUST delete checkpoints older than `AI_CHECKPOINT_EXPIRY_HOURS` (default 24 hours) where `completed_at` IS NOT NULL. Incomplete checkpoints older than 48 hours MUST also be cleaned up and their associated proposals marked as `EXPIRED`.

3. **Tier Routing Config Cache:** The tier routing configuration MUST be cached in-memory with a TTL of 60 seconds. Cache reads must not acquire a database connection. The `reload_config()` endpoint bypasses the cache and refreshes from the database immediately.

---

## Section 5 — Current State Assessment

### 5.1 What Exists

1. **US-AI-026 (Model Router):** A `ModelRouter` service exists with primary/fallback model logic. The router accepts a `model_id` parameter (or uses the default) and handles provider-level fallback (timeout, rate limit, server error). It does not currently distinguish between model tiers.

2. **US-AI-023 (Chat Orchestrator):** The chat orchestrator invokes the model router directly for all LLM interactions. There is no separation between structural "planning" prompts and content "generation" prompts. A single system prompt is used for the entire interaction loop.

3. **Configuration Variables:** `AI_PRIMARY_MODEL`, `AI_FALLBACK_MODEL`, `AI_MODEL_TIMEOUT_SECONDS`, `AI_MODEL_MAX_TOKENS`, `AI_MODEL_TEMPERATURE`. These are single-valued; they do not support tier-specific configuration.

4. **Proposal Persistence:** `ai_proposals` table (US-AI-004) stores proposal lifecycle data. No checkpoint mechanism exists for multi-phase generation workflows.

5. **Telemetry:** Basic model-level telemetry exists (model ID, latency, token count). No tier-specific metrics are emitted.

### 5.2 What Must Be Built

1. **`app/services/ai/tier_orchestrator.py`:** The two-tier workflow orchestration service. This is the primary new component. It coordinates the planner invocation, checkpoint write, context pruning handoff, generator invocation, and retry logic. (Estimated: 350-450 lines)

2. **`app/services/ai/planner_service.py`:** The planner model invocation service. Handles planner-specific prompt construction, output parsing, and output validation against the planner output schema. (Estimated: 200-300 lines)

3. **`app/services/ai/generator_service.py`:** The generator model invocation service. Handles generator-specific prompt construction (injecting planner output), schema-bound validation, retry with validation feedback, and integration with US-AI-027 JSON repair. (Estimated: 250-350 lines)

4. **`app/services/ai/checkpoint_service.py`:** The atomic checkpoint read/write service for the `ai_generation_checkpoints` table. Provides idempotent write, versioned read, and expiry operations. (Estimated: 150-200 lines)

5. **`app/services/ai/tier_routing_config.py`:** Configuration loader and cache for the tier routing matrix. Supports runtime reload. (Estimated: 100-150 lines)

6. **Database Migration:** Alembic migration script creating `ai_generation_checkpoints` table, `ai_tier_routing_config` table, and ALTER TABLE scripts for `ai_sessions` and `ai_audit_logs`. (Estimated: 1 migration script)

### 5.3 What Must Be Modified

1. **`app/services/ai/model_router.py` (US-AI-026):** Augment the `call_model()` signature to accept an optional `model_tier: str` parameter. Add tier-aware fallback logic: when a planner-tier model fails, fall back to other planner-tier providers, not to generator-tier providers. Add a `call_planner(input, timeout)` and `call_generator(input, timeout)` method that apply tier-specific configuration (model, timeout, max_tokens, temperature).

2. **`app/services/ai/cost_tracker.py` (US-AI-036):** Add `model_tier` column to the usage record. Add tier-specific budget cap enforcement. Add tier-attribution in cost calculation: planner models use `AI_PLANNER_MODEL` pricing, generator models use `AI_GENERATOR_MODEL` pricing.

3. **`app/services/ai/context_pruner.py` (US-AI-028):** Modify the pruning algorithm to accept the planner output as a hint. If the planner selected `templateType=text-content`, prune tabs, accordion, click-reveal, and final-assessment schemas from the generator context. If the planner selected `templateType=final-assessment`, prune all non-assessment schemas.

4. **`app/services/ai/prompt_manager.py` (US-AI-042):** Add `model_tier` as a discriminator column to `ai_prompt_versions`. The prompt resolver selects a prompt version by both `active` status AND `model_tier` matching the current operation. Planner prompts and generator prompts are versioned independently.

5. **`app/services/ai/chat_orchestrator.py` (US-AI-023):** Modify the generation path to call `TierOrchestrator.generate_page_content()` instead of directly invoking the model router. Conversational replies and clarification requests continue to use the planner tier directly via the model router.

---

## Section 6 — Expansion Points

### 6.1 Technical Expansion Points

1. **Three-Tier Architecture (Planner + Generator + Validator):** The current two-tier model could be expanded to a three-tier architecture where a third, specialized model tier handles validation and refinement. After the generator produces content, a dedicated validator model (potentially a fine-tuned small model) runs a targeted quality check against template rules, SCORM requirements, and accessibility standards. This validator tier would have even stricter latency requirements (< 500 ms) and could operate asynchronously, reporting issues without blocking the generation workflow. The checkpoint service would gain a third phase: `validation_proposed`.

2. **Fine-Tuned Planner Model:** As the system accumulates planning decisions (template selections, structural choices) with their acceptance rates from RLHF feedback (US-AI-031), a fine-tuned planner model could be trained to match accepted patterns more closely. The planner checkpoint data would serve as training data: each checkpoint with an `accepted` or `rejected` label forms a training example. A/B testing (US-AI-042) would compare the general-purpose planner against the fine-tuned planner.

3. **Speculative Planning Decoding:** For batch generation workflows (US-AI-029), the planner could produce multiple structural hypotheses in parallel at minimal marginal cost. Each hypothesis is scored by a lightweight heuristic (template-type validity, page-count reasonableness), and the highest-scoring hypothesis is passed to the generator. This increases planner latency slightly (parallel calls) but reduces the risk of the generator working from a poor structural plan.

### 6.2 Functional Expansion Points

1. **Per-Template-Type Planner Model Selection:** The tier routing matrix could be extended to support per-template-type model selection within the planner tier. For example, planning a "final-assessment" might require a more capable planner model than planning a "text-content" page. The `assigned_tier` field in `ai_tier_routing_config` could become `planner:high`, `planner:low`, `generator:high`, `generator:standard` to express different capability levels within a tier.

2. **User-Configurable Speed/Quality Slider:** An advanced user preference could expose a "speed vs. quality" slider in the AI settings: "Faster (cheaper)" forces both planner and generator to fast/cheap models, "Best quality" forces premium models for both tiers, "Balanced (default)" uses the configured tier matrix. This maps to the `tier_override` field on the session: `force_planner` = fast mode, `force_generator` = quality mode, `auto` = balanced.

3. **Tier Cost Alerts and Quotas:** The tier-based cost attribution enables fine-grained budget policies: "Planner-tier spending must not exceed 30% of total AI budget per tenant" or "Generator-tier spending gets 2x budget in December for end-of-year course creation." These policies would be enforced by the cost tracker (US-AI-036) with tier-specific thresholds and webhook notifications when approaching limits.

---

## Section 7 — Validation and Testing

### 7.1 Unit Tests

**UT-PLANNER-01 (Planner Output Schema Validation):** Given a valid planner output with `templateType`, `contentBrief`, and optional `structureHint`, the `validate_planner_output()` function returns success. Given a planner output with `templateType` set to an unsupported value (e.g., `"video"`), the function raises `PlannerOutputValidationError`. Given a planner output with `contentBrief` exceeding 2000 characters, the function raises `PlannerOutputValidationError`.

**UT-PLANNER-02 (Planner Tier Fallback Chain):** Given a mock model router that raises `TimeoutError` for the primary planner model and succeeds for the fallback planner model, the `TierOrchestrator` invokes the primary, falls back to the fallback, and returns a successful `PlannerResponse` with `fallback_occurred=True`. The planner checkpoint is written successfully. No generator-tier model is invoked as a fallback unless `AI_ALLOW_LAST_RESORT_PLANNER` is true.

**UT-PLANNER-03 (Planner All-Fallback Exhaustion):** Given a mock model router that raises `TimeoutError` for all configured planner-tier models and `AI_ALLOW_LAST_RESORT_PLANNER=false`, the `TierOrchestrator` raises `AIServiceUnavailable` with message containing "planner". No checkpoint is written. The proposal status is set to `FAILED`.

**UT-GENERATOR-01 (Generator Retry on Validation Failure):** Given a mock generator that produces invalid template data on the first call (a tabs page with 1 item) and valid data on the second call, the `GeneratorService` invokes the generator twice. The first call's validation error is included in the second call's input. The function returns the corrected data from the second call. `generator_retry_count` is 1.

**UT-GENERATOR-02 (Generator Retry Budget Exhaustion):** Given a mock generator that produces invalid data on every call up to `AI_GENERATOR_MAX_RETRIES + 1`, the `GeneratorService` exhausts its retry budget and raises `AIGenerationFailed`. All retry attempts are logged with validation error details. The checkpoint remains at `planning_complete` phase.

**UT-GENERATOR-03 (Generator Fallback to Alternative Provider):** Given a mock primary generator model that raises `APITimeoutError` and a fallback generator model that succeeds, the `GeneratorService` invokes the fallback. The returned `GeneratorResponse` has `fallback_occurred=True`. The checkpoint is updated with `generator_fallback_used=True` and the fallback provider identifier.

**UT-CHECKPOINT-01 (Checkpoint Idempotent Write):** Given a `(proposal_id, 'planning_complete')` checkpoint that already exists, `write_planner_checkpoint()` returns the existing checkpoint without creating a duplicate row. The function does not modify the existing row. The `UNIQUE` index constraint on `idx_checkpoints_proposal_phase` ensures no duplicates at the database level.

**UT-CHECKPOINT-02 (Checkpoint Recovery):** Given an existing checkpoint with `phase='planning_complete'` and `completed_at IS NULL`, `get_planner_checkpoint()` returns the checkpoint data including the full `planner_output` JSON. The orchestrator reconstructs the `PlannerOutput` from the checkpoint data and proceeds to the generator phase without re-invoking the planner.

**UT-CONFIG-01 (Tier Routing Configuration Load and Validate):** Given a valid tier routing JSON file with all 10 task types mapped to valid tiers, `TierRoutingConfig.load()` succeeds. Given a JSON file with a missing task type, `load()` fills the gap with the default tier. Given a JSON file with an invalid tier value (e.g., `"ultra"`), `load()` raises `ConfigurationError`.

**UT-METRICS-01 (Workflow Metrics Collection):** Given a successful planner invocation and a successful generator invocation with retry, the `build_workflow_metrics()` function returns a `WorkflowMetrics` object with all fields populated: `planner_latency_ms`, `planner_token_input`, `planner_model_id`, `generator_latency_ms`, `generator_token_output`, `generator_retries=1`, `planner_to_generator_token_ratio` computed correctly.

### 7.2 Integration Tests

**IT-PLANNER-GENERATOR-01 (Full Two-Tier Generation Flow):** Set up a mock LLM provider that returns deterministic responses. Configure a planner model mock that returns a valid `PlannerOutput` for any input. Configure a generator model mock that returns valid template data matching the planner's template selection. Execute `TierOrchestrator.generate_page_content()`. Verify: (a) planner mock is called exactly once, (b) checkpoint is written after planner success, (c) generator mock is called exactly once with the planner output injected into its context, (d) the returned `GeneratorResponse` contains valid template data, (e) workflow metrics are emitted with correct values.

**IT-PLANNER-GENERATOR-02 (Generator Retry Flow with Validation):** Set up a generator mock that returns invalid template data (missing required field) on the first two calls and valid data on the third call. Configure `AI_GENERATOR_MAX_RETRIES=2`. Execute generation flow. Verify: (a) generator mock is called 3 times (initial + 2 retries), (b) each retry includes the previous validation error messages in its input, (c) the returned data is valid, (d) checkpoint reflects `generator_retry_count=2`.

**IT-CHECKPOINT-RECOVERY-01 (Crash Recovery After Planner):** Simulate an orchestrator crash after the planner checkpoint is written but before generator completion. Call `recover_generation(session_id, proposal_id)`. Verify: (a) the recovery function reads the existing checkpoint, (b) the planner is NOT re-invoked, (c) the generator is invoked with the recovered planner output, (d) a new checkpoint row is NOT created (the existing row is updated with generator metadata).

**IT-TIER-OVERRIDE-01 (Force Generator Mode):** Set session `tier_override=force_generator`. Execute generation flow. Verify: (a) planner is NOT invoked, (b) the generator receives a combined system prompt that includes both structural instructions and content generation instructions, (c) the returned output is valid, (d) audit record shows `model_tier='generator'` and no checkpoint phase `planning_complete`.

**IT-TIER-OVERRIDE-02 (Force Planner Mode):** Set session `tier_override=force_planner`. Execute generation flow. Verify: (a) planner is invoked as normal, (b) generator is NOT invoked, (c) the planner output serves as the final content, (d) checkpoint shows only `planning_complete` phase, (e) the proposal is created with the planner output's content brief as the page content.

### 7.3 End-to-End Tests

**E2E-TIER-01 (Author Creates Page Via Chat — Two-Tier Transparent):** Using the AI chat UI, the user types "Create a page introducing project management with a text overview and a comparison of methodologies." The system uses the planner tier to determine structure (template selection, page outline) and the generator tier to produce full content. Verify: (a) the user sees a single unified AI response (no indication of two-tier architecture), (b) the generated page has correct template type and content matching the request, (c) audit log records both planner and generator model IDs with distinct tier attribution, (d) the admin dashboard shows per-tier cost breakdown for this session.

**E2E-TIER-02 (Planner Failure With Generator Fallback Recovery):** Using the admin advanced settings, disable the primary and fallback planner models. Enable `AI_ALLOW_LAST_RESORT_PLANNER=true`. The user creates a page via chat. Verify: (a) the user sees the page successfully created (no error visible), (b) the admin audit log shows `tier_fallback_used=true` and `tier_fallback_reason='all_planner_models_failed_used_generator_tier'`, (c) the admin telemetry dashboard shows a spike in the "last resort planner used" counter, (d) the checkpoint records `planner_last_resort=true`.

### 7.4 Manual QA Steps

1. **Tier Routing Matrix Validation:** Log into the admin panel. Navigate to AI Configuration > Tier Routing. Verify all 10 task types are listed with their assigned tiers. Change the `page_content_generation` task type from `generator` to `planner`. Create a page via AI chat. Verify that the system attempts to use the planner model for content generation and that the output quality is visibly lower (shorter content, less structured). Reset the configuration. Verify the configuration takes effect within 60 seconds without server restart.

2. **Tier Cost Attribution:** Execute a session that creates 3 pages: one text-content, one tabs, and one final-assessment. Navigate to Admin > Cost Tracking. Verify: (a) the cost breakdown widget shows separate planner and generator costs, (b) the planner-to-generator cost ratio is approximately 1:5 to 1:20 (planner cost per call is significantly lower), (c) the per-page cost breakdown shows one planner call and one generator call per page (3 planner + 3 generator = 6 model calls total).

3. **Generator Retry Debugging:** Configure the generator model to intentionally produce invalid JSON (using a mock or test endpoint). Set `AI_GENERATOR_MAX_RETRIES=2`. Submit a page creation request. Monitor the logs. Verify: (a) the generator is called 3 times (1 initial + 2 retries), (b) each retry includes progressively more validation error context, (c) after the third failure, the proposal is marked `FAILED` with reason `generation_failed_after_retries`, (d) the user sees the error "AI was unable to generate valid content for this page. Please try again or rephrase your request."

4. **Checkpoint Expiry Cleanup:** Using direct database access, create a checkpoint row with `created_at = NOW() - INTERVAL '25 hours'` and `completed_at = NOW() - INTERVAL '24 hours'`. Run the checkpoint cleanup job manually. Verify the row is deleted. Create a checkpoint row with `created_at = NOW() - INTERVAL '49 hours'` and `completed_at IS NULL`. Run the cleanup job. Verify the row is deleted and the associated proposal is marked `EXPIRED`.

5. **Planner Output Boundary Security:** Using the admin audit view (US-AI-020), inspect the `planner_output_snapshot` for a completed generation. Verify the planner output is stored as a JSONB field with the exact schema: `templateType`, `contentBrief`, optional `structureHint`, optional `sourceMaterial`. Verify the generator output does NOT duplicate the planner output — the audit record links them via `generation_checkpoint_id`.

---

## Section 8 — Definition of Done

The following checklist items MUST all be completed for this story to be considered done.

1. [ ] **Tier Routing Config Table:** The `ai_tier_routing_config` table exists in the database, seeded with default routing rules for all 10 task types. The `TierRoutingConfig` service loads and caches the configuration at startup.

2. [ ] **Planner Service:** `app/services/ai/planner_service.py` exists and implements: planner-specific system prompt construction, model invocation via US-AI-026 with planner-tier configuration, output parsing against the planner output schema, and structured error handling for invalid planner output.

3. [ ] **Generator Service:** `app/services/ai/generator_service.py` exists and implements: generator-specific system prompt construction with planner output injection, model invocation via US-AI-026 with generator-tier configuration, schema validation against template JSON schemas, retry logic with validation error feedback, and integration with US-AI-027 JSON repair.

4. [ ] **Tier Orchestrator:** `app/services/ai/tier_orchestrator.py` exists and implements the two-tier workflow: planner invocation with fallback, atomic checkpoint write, context pruning handoff to US-AI-028, generator invocation with retry, workflow metrics emission, and crash recovery from planner checkpoints.

5. [ ] **Checkpoint Service:** `app/services/ai/checkpoint_service.py` exists and implements: idempotent checkpoint write for `planning_complete`, checkpoint update for `generation_complete` and `validation_complete`, checkpoint read by proposal_id, checkpoint expiry and cleanup, and unique constraint enforcement (one `planning_complete` checkpoint per proposal).

6. [ ] **Database Migrations:** Alembic migration scripts exist and are tested for: (a) creating `ai_generation_checkpoints` table with all columns, constraints, and indexes, (b) creating `ai_tier_routing_config` table with seed data, (c) ALTER TABLE `ai_sessions` to add tier override and cost accumulation columns, (d) ALTER TABLE `ai_audit_logs` to add tier tracking columns. All migrations are reversible.

7. [ ] **Model Router Extension (US-AI-026):** The `ModelRouter` service accepts a `model_tier` parameter and applies tier-specific configuration (model ID, timeout, max_tokens, temperature). Tier-aware fallback ensures planner models fall back within the planner tier, generator models within the generator tier.

8. [ ] **Cost Tracker Extension (US-AI-036):** Usage records include a `model_tier` column. Cost calculations are tier-aware. The cost dashboard displays per-tier breakdown. Budget caps can be configured per tier.

9. [ ] **Audit Extension (US-AI-020):** Every applied AI mutation records: `model_tier`, `planner_output_snapshot`, `generation_checkpoint_id`, `tier_fallback_used`, and `tier_fallback_reason` in the audit log.

10. [ ] **Telemetry Metrics:** The following metrics are emitted and visible in the observability dashboard (US-AI-021): `ai_planner_latency_ms` (histogram), `ai_generator_latency_ms` (histogram), `ai_checkpoint_write_ms` (histogram), `ai_tier_handoff_ms` (histogram), `ai_generator_retry_count` (counter), `ai_planner_fallback_count` (counter), `ai_generator_fallback_count` (counter), `ai_last_resort_planner_count` (counter). All metrics are tagged with `tenant_id`, `template_type`, and `workflow_type`.

11. [ ] **Recovery From Planner Checkpoint:** If the orchestrator process crashes after the planner checkpoint is written, the recovery process detects the incomplete checkpoint and resumes from the `planning_complete` phase without re-invoking the planner. Tested in integration test IT-CHECKPOINT-RECOVERY-01.

12. [ ] **Tier Override Functionality:** The `tier_override` field on `ai_sessions` functions correctly for all three values: `auto` (use configured routing matrix), `force_planner` (skip generator, use planner output as content), `force_generator` (skip planner, use combined prompt). Override is validated server-side; only `ai_admin` role can set non-auto values. Tested in integration tests IT-TIER-OVERRIDE-01 and IT-TIER-OVERRIDE-02.

13. [ ] **Configuration File and Runtime Reload:** The `config/ai_tier_routing.json` file is loaded at startup and parsed into `TierRoutingConfig`. The `reload_config()` endpoint re-reads the file and updates the in-memory cache without server restart. Invalid configuration files are rejected at startup with a clear error message. Tested in unit test UT-CONFIG-01.

14. [ ] **End-User Transparency:** The AI chat UI (US-AI-024) shows no indication of the two-tier architecture. All tier routing, fallback, and checkpoint operations are transparent to the end user. Verified in E2E test E2E-TIER-01 and manual review.

15. [ ] **Planner Output Security Boundary:** The planner output injected into the generator's system prompt is wrapped in strict data boundary markers. The generator prompt explicitly instructs the model that the planner output is data, not instructions. Verified by code review and penetration test of prompt injection scenarios.

16. [ ] **All Unit Tests Pass:** All 12 unit tests (UT-PLANNER-01 through UT-CONFIG-01, UT-METRICS-01) pass with >90% code coverage for the new services (`tier_orchestrator.py`, `planner_service.py`, `generator_service.py`, `checkpoint_service.py`, `tier_routing_config.py`).

17. [ ] **All Integration Tests Pass:** All 5 integration tests (IT-PLANNER-GENERATOR-01 through IT-TIER-OVERRIDE-02) pass against a real PostgreSQL database instance with mocked LLM provider responses.

18. [ ] **All E2E Tests Pass:** Both E2E tests (E2E-TIER-01, E2E-TIER-02) pass against a full deployment with mocked LLM providers.

---

## Section 9 — Tasks and Sub-Tasks

| ID | Task | Sub-Tasks | Estimated Effort | Dependencies | Assigned To |
|---|---|---|---|---|---|
| T1 | **Create database schema for generation checkpoints and tier routing** | T1.1 Write Alembic migration for `ai_generation_checkpoints` table with all columns, constraints, indexes, and foreign keys. T1.2 Write Alembic migration for `ai_tier_routing_config` table with seed data for all 10 task types. T1.3 Write Alembic migration for ALTER TABLE `ai_sessions` (add tier_override, planner_cost_accumulated, generator_cost_accumulated). T1.4 Write Alembic migration for ALTER TABLE `ai_audit_logs` (add model_tier, planner_output_snapshot, generation_checkpoint_id, tier_fallback_used, tier_fallback_reason). T1.5 Write rollback scripts for all migrations. T1.6 Create SQLAlchemy ORM models for `AIGenerationCheckpoint` and `AITierRoutingConfig`. T1.7 Run migrations against local PostgreSQL and verify schema. | 2 days | US-AI-004 (AI Persistence Foundations) | Backend Engineer |
| T2 | **Implement Tier Routing Configuration Service** | T2.1 Create `app/services/ai/tier_routing_config.py` with `TierRoutingConfig` Pydantic model and `TierRoutingConfigLoader` class. T2.2 Implement `load_from_db()` method reading from `ai_tier_routing_config` table. T2.3 Implement `load_from_file(path)` method reading from JSON configuration file. T2.4 Implement in-memory cache with 60-second TTL. T2.5 Implement `reload_config()` endpoint that bypasses cache and refreshes from database. T2.6 Implement `get_tier_for_task(task_type)` method. T2.7 Add startup validation: log warning if any task type is missing from configuration. T2.8 Write unit tests (UT-CONFIG-01). T2.9 Update application startup to initialize and validate tier routing config. | 1.5 days | US-AI-003 (Isolated AI API Module) | Backend Engineer |
| T3 | **Extend Model Router for Tier-Aware Routing** | T3.1 Add `model_tier: str` parameter to `ModelRouter.call_model()` signature. T3.2 Create `call_planner()` method that applies `AI_PLANNER_MODEL`, `AI_PLANNER_TIMEOUT_SECONDS`, `AI_PLANNER_MAX_TOKENS`, `AI_PLANNER_TEMPERATURE` configuration. T3.3 Create `call_generator()` method that applies `AI_GENERATOR_MODEL`, `AI_GENERATOR_TIMEOUT_SECONDS`, `AI_GENERATOR_MAX_TOKENS`, `AI_GENERATOR_TEMPERATURE` configuration. T3.4 Implement tier-aware fallback: planner falls back to `AI_PLANNER_FALLBACK_MODEL`, generator falls back to `AI_GENERATOR_FALLBACK_MODEL`. T3.5 Add `model_tier` to the telemetry tags emitted for each model call. T3.6 Add `model_tier` to the audit log fields. T3.7 Write unit tests for tier-aware routing fallback. T3.8 Update existing model router tests to pass with new parameter. | 2 days | US-AI-026 (Multi-Provider Model Routing) | Backend Engineer |
| T4 | **Implement Planner Service** | T4.1 Create `app/services/ai/planner_service.py` with `PlannerService` class. T4.2 Implement `build_planner_prompt()` method: load planner system prompt from `ai_prompt_versions`, inject user_prompt, course_context, available_templates. T4.3 Implement `invoke_planner()` method: call `ModelRouter.call_planner()`, parse structured output, validate against `PlannerOutput` Pydantic schema. T4.4 Implement `validate_planner_output()`: check `templateType` is in allowed list, `contentBrief` within max length, `structureHint` keys match allowed structure hints per template type. T4.5 Implement `PlannerInput` and `PlannerOutput` Pydantic models. T4.6 Handle error cases: empty output, invalid template type, malformed JSON, missing required fields. T4.7 Write unit tests (UT-PLANNER-01, UT-PLANNER-02, UT-PLANNER-03). | 2 days | T3 (Model Router Extension) | Backend Engineer |
| T5 | **Implement Generator Service** | T5.1 Create `app/services/ai/generator_service.py` with `GeneratorService` class. T5.2 Implement `build_generator_prompt()` method: load generator system prompt, inject planner output with security boundaries, inject template JSON schema, inject pruned context, inject validation errors if retry. T5.3 Implement `invoke_generator()` method: call `ModelRouter.call_generator()`, attempt JSON parse, delegate to US-AI-027 repair on parse failure, validate against template JSON schema. T5.4 Implement retry logic: capture validation errors, append to `GeneratorInput.validation_errors`, increment `retry_number`, re-invoke generator. T5.5 Enforce `AI_GENERATOR_MAX_RETRIES` limit; on exhaustion raise `AIGenerationFailed` with retry trace. T5.6 Implement `GeneratorInput`, `GeneratorResponse` Pydantic models. T5.7 Wire JSON repair service (US-AI-027) as optional dependency. T5.8 Write unit tests (UT-GENERATOR-01, UT-GENERATOR-02, UT-GENERATOR-03). | 2.5 days | T4 (Planner Service), US-AI-027 (JSON Repair) | Backend Engineer |
| T6 | **Implement Checkpoint Service** | T6.1 Create `app/services/ai/checkpoint_service.py` with `CheckpointService` class. T6.2 Implement `write_planner_checkpoint()`: INSERT into `ai_generation_checkpoints` with phase=`planning_complete`. Handle unique constraint violation by returning existing checkpoint (idempotent). T6.3 Implement `update_generator_checkpoint()`: UPDATE the planning_complete row with generator metadata and phase=`generation_complete`. T6.4 Implement `get_planner_checkpoint(proposal_id)`: SELECT the planning_complete checkpoint for the given proposal. T6.5 Implement `expire_session_checkpoints(session_id)`: UPDATE all incomplete checkpoints for a session to phase=`failed`. T6.6 Implement `cleanup_expired_checkpoints()`: DELETE checkpoints beyond TTL, mark associated proposals as EXPIRED. T6.7 Write unit tests (UT-CHECKPOINT-01, UT-CHECKPOINT-02). | 1.5 days | T1 (Database Schema) | Backend Engineer |
| T7 | **Implement Tier Orchestrator** | T7.1 Create `app/services/ai/tier_orchestrator.py` with `TierOrchestrator` class. T7.2 Implement `generate_page_content()` method following the two-tier flow pseudocode in Section 3.1.4. T7.3 Implement planner fallback loop: primary planner -> planner fallback providers -> optional last-resort generator-tier planner. T7.4 Implement generator retry loop: initial generation -> retries with validation feedback -> exhaustion failure. T7.5 Implement `build_workflow_metrics()`: aggregate planner and generator telemetry into single `WorkflowMetrics` object. T7.6 Implement `emit_workflow_telemetry()`: push metrics to observability system (US-AI-021). T7.7 Implement crash recovery path: detect incomplete checkpoint, resume from `planning_complete`. T7.8 Handle `tier_override` session field: `force_planner` bypasses generator, `force_generator` bypasses planner, `auto` uses routing config. T7.9 Implement `WorkflowMetrics` Pydantic model. T7.10 Write integration tests (IT-PLANNER-GENERATOR-01, IT-PLANNER-GENERATOR-02, IT-CHECKPOINT-RECOVERY-01, IT-TIER-OVERRIDE-01, IT-TIER-OVERRIDE-02). | 3 days | T4, T5, T6 (Planner, Generator, Checkpoint Services) | Backend Engineer |
| T8 | **Extend Cost Tracker for Tier Attribution** | T8.1 Add `model_tier` column to usage record schema in `ai_usage_records` table. T8.2 Update `CostTracker.record_usage()` to accept `model_tier` parameter. T8.3 Implement tier-specific cost calculation: planner tokens priced at `AI_PLANNER_MODEL` rate, generator tokens at `AI_GENERATOR_MODEL` rate. T8.4 Add `get_tier_cost_summary(tenant_id, date_range)` query for dashboard. T8.5 Add tier-specific budget cap enforcement: `AI_PLANNER_MONTHLY_COST_CAP`, `AI_GENERATOR_MONTHLY_COST_CAP`. T8.6 Update existing cost dashboard UI component to show tier breakdown. T8.7 Write integration tests for tier-specific cost calculation and budget enforcement. | 1.5 days | US-AI-036 (Cost Tracking) | Backend Engineer |
| T9 | **Extend Context Pruner for Planner Output Integration** | T9.1 Modify `ContextPruner.prune()` to accept optional `PlannerOutput` parameter. T9.2 When planner output provides `templateType`, prune all template schemas that do not match the selected template type. T9.3 Implement template-category pruning: if `templateType=text-content`, prune assessment-specific schemas (questions, scoring) as well as interaction schemas (tabs items, accordion panels, click-reveal triggers). T9.4 Ensure safety schemas (always-include: validation rules, tool definitions) are never pruned regardless of planner output. T9.5 Write unit tests for planner-output-driven context pruning. | 1 day | US-AI-028 (Context Pruning) | Backend Engineer |
| T10 | **Extend Prompt Manager for Tier-Specific Prompts** | T10.1 Add `model_tier` discriminator column to `ai_prompt_versions` table. T10.2 Implement `resolve_prompt(version_id, model_tier)` method that selects the prompt version matching both the active status and the model tier. T10.3 Create initial planner system prompt: focuses on structure, template selection, content outlining. Strict instruction: "Do NOT generate full content. Output only structural JSON." T10.4 Create initial generator system prompt: receives planner output as data, focuses on schema-compliant content generation. T10.5 Write unit tests for tier-prompt resolution. T10.6 Seed `ai_prompt_versions` with initial planner and generator prompts at version 1. | 1.5 days | US-AI-042 (Prompt Versioning) | Backend Engineer |
| T11 | **Update Chat Orchestrator for Two-Tier Integration** | T11.1 Modify `ChatOrchestrator.process_turn()` to detect content-generation tasks and route through `TierOrchestrator.generate_page_content()`. T11.2 Keep conversational replies and clarification requests on the planner-tier direct path (no generator needed). T11.3 Ensure existing single-turn behavior is unchanged for non-generation flows. T11.4 Add `tier_workflow_id` to chat turn metadata tracking. T11.5 Write integration tests verifying content-generation tasks use two-tier path while conversational replies use single-tier path. T11.6 Write regression tests ensuring existing chat behavior is unchanged. | 2 days | US-AI-023 (AI Chat Endpoint), T7 (Tier Orchestrator) | Backend Engineer |
| T12 | **Write E2E Tests and Manual QA Scripts** | T12.1 Write E2E test E2E-TIER-01: create page via chat, verify transparent two-tier execution, verify audit trails, verify no user-facing tier indication. T12.2 Write E2E test E2E-TIER-02: simulate planner failure with generator-tier last-resort fallback, verify recovery and audit trails. T12.3 Write manual QA script for tier routing matrix validation (Manual QA Step 1). T12.4 Write manual QA script for tier cost attribution verification (Manual QA Step 2). T12.5 Write manual QA script for generator retry debugging (Manual QA Step 3). T12.6 Write manual QA script for checkpoint expiry cleanup (Manual QA Step 4). T12.7 Write manual QA script for planner output boundary security (Manual QA Step 5). | 2 days | T7, T11 (Tier Orchestrator, Chat Orchestrator Integration) | QA Engineer |

**Total Estimated Effort:** 21 days (approximately 4-5 sprints of 2 weeks, or a focused 3-week engineering push with 2 engineers).
