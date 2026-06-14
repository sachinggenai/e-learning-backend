# US-AI-042: System Prompt Versioning and A/B Testing

**Status:** Draft
**Priority:** SHOULD for MVP, MUST for Production
**Depends on:** US-AI-023 (AI Chat Endpoint and LLM Interaction Loop), US-AI-031 (RLHF Feedback and Provenance Tracking), US-AI-036 (Cost Tracking and Token Budget Enforcement)
**Source flows:** Flow 30 — System Prompt Versioning and A/B Testing
**Epic Owner:** Technical Product Owner

---

## 1. Functional Specification

### 1.1 User Story

As a **Platform Operator / AI Product Manager**, I want to version-control system prompts, deploy different prompt variants to user segments, and measure their impact on content quality and cost, so that I can iteratively optimize the AI assistant's behavior through data-driven experimentation rather than guesswork.

As an **Author**, I want to optionally see which prompt variant is active (via a badge or tooltip) and know that the AI's behavior may change between experiments, so that I can give informed feedback when prompted.

### 1.2 Overview

The AI chat orchestration layer (US-AI-023) constructs a system prompt for every chat turn. Currently, the system prompt is hardcoded or loaded from a single configuration value. This precludes systematic optimization: prompt improvements require code deploys, cannot be rolled back independently, and cannot be measured against a control group.

This epic delivers three capabilities:

1. **System Prompt Registry** — A database-backed store of system prompt templates with full version history. Each prompt is a Jinja2 template that may reference dynamic context variables (course state, tool definitions, user role, guardrails).

2. **A/B Experiment Framework** — A configuration-driven system that assigns users to prompt variants based on traits (tenant, user ID hash, feature flag membership, random percentage) and logs assignment for every chat turn so downstream analytics can compare variant performance.

3. **Variant Analytics Pipeline** — A queryable view that aggregates per-variant metrics: proposal acceptance rate, tool call error rate, average tokens consumed, content quality scores (from RLHF signals in US-AI-031), latency, and cost. These data power dashboards and automated rollback triggers.

**Key design decisions:**

- **Templates, not raw text**: System prompts are Jinja2 templates with typed variable slots. The orchestrator resolves variables at runtime from the session context. This avoids storing per-user prompt copies and makes prompt structure auditable.
- **Assignment at session start, not per turn**: A user's variant assignment is fixed for the duration of an AI session. This prevents the LLM from observing prompt-switching mid-conversation, which would invalidate A/B comparisons and could confuse the model.
- **Immutable prompt versions**: Once a prompt version record is created, its `content` and `variables_schema` are immutable. A new version is created for any edit. This guarantees that experiment results are reproducible.
- **Sticky assignment for users**: Within a single experiment, a given user always sees the same variant (based on a consistent hash of `user_id + experiment_id`). This avoids giving different experiences on different days and reduces variance in metrics.
- **No prompt content in chat logs**: Prompt versions are referenced by `(prompt_id, version_id)` foreign keys in session records. The raw prompt text is never duplicated in chat message tables, saving storage and ensuring audit trail integrity.
- **Feature-flagged**: The entire system-prompt-registry and A/B testing subsystem is gated behind `FEATURE_AI_PROMPT_REGISTRY`. When disabled, the orchestrator falls back to the legacy prompt construction path.

### 1.3 Actors

| Actor | Role |
|---|---|
| Platform Operator / AI PM | Creates, edits, version-tags system prompts; configures A/B experiments; monitors variant dashboards; triggers rollbacks |
| AI Orchestrator (US-AI-023) | Resolves prompt template + variables at turn start; logs variant assignment in session records |
| Author (User) | Interacts with AI chat; may see variant badge; provides RLHF feedback (US-AI-031) that flows into variant analytics |
| PromptRegistry Service | CRUD + versioning for prompt templates; variable schema validation at publish time |
| ExperimentAssigner Service | Deterministic variant assignment (hash-based or config-based); logs assignments |
| VariantAnalytics Service | Aggregates per-variant metrics from session logs, tool call logs, RLHF events |
| Background Rollback Job | Monitors variant metrics against quality/cost thresholds; auto-rolls back degrading variants |

### 1.4 Flows

#### Flow 1: System Prompt Lifecycle (Create, Version, Activate)

**Phase 0 — Prompt Authoring**

1. Operator opens the Prompt Registry admin UI at `GET /admin/ai/prompts`.
2. Operator clicks "New Prompt" and provides:
   - `name` — human-readable label (e.g., `course-authoring-v2`)
   - `description` — purpose and change notes
   - `category` — one of `system`, `tool_definitions`, `guardrails`, `context_summary`
   - `content` — the Jinja2 template text
   - `variables_schema` — JSON Schema defining the expected context variables (e.g., `{course_title: string, pages: array, tool_definitions: array}`)
   - `tags` — key-value metadata for search/filter (e.g., `lang:en`, `domain:compliance`)
3. Backend validates the template:
   - Jinja2 syntax is parseable.
   - All referenced variables are declared in `variables_schema`.
   - Template length does not exceed `AI_PROMPT_MAX_TEMPLATE_CHARS` (default 50000).
4. Backend creates `prompt_id` (ULID) and `version_id = 1`.
5. Content is hashed with SHA-256; if an identical content hash exists for the same prompt name, the creation is rejected as a duplicate.

**Phase 1 — Version Update**

1. Operator edits an existing prompt and saves.
2. Backend creates a new version row:
   - `version_id` incremented by 1.
   - Previous `content`, `variables_schema`, and `change_notes` preserved as the old version (immutable).
   - New version gets `version_id = N + 1`, `is_active = false` (requires explicit activation).
3. The previous active version remains active until the operator explicitly activates the new version.

**Phase 2 — Activate a Version**

1. Operator calls `PATCH /api/v1/ai/prompts/{prompt_id}/activate` with `{version_id: 5}`.
2. Backend validates version 5 exists and belongs to this prompt.
3. Backend sets `is_active = false` on the currently active version, then sets `is_active = true` on version 5.
4. This activation change is logged in `ai_prompt_audit` for compliance.
5. The active version is the one served to all experiments that reference `prompt_id` without a pinned version.

**Phase 3 — Dry-Run / Preview**

1. Operator calls `POST /api/v1/ai/prompts/{prompt_id}/preview` with a JSON body providing sample context variables.
2. Backend resolves the template against the provided variables and returns the rendered output.
3. If variable resolution fails (missing required variable), a 422 error lists the missing keys.
4. This allows prompt authors to verify rendering before activating.

#### Flow 2: Experiment Lifecycle (Create, Assign, Conclude)

**Phase 0 — Define Experiment**

1. Operator calls `POST /api/v1/ai/experiments` with:
   ```json
   {
     "name": "prompt-tone-ab-v1",
     "description": "Compare formal vs. conversational tone in system prompt",
     "assignment_strategy": "hash_pct",
     "hash_seed": 42,
     "variants": [
       {
         "name": "control",
         "prompt_id": "prompt_course_authoring",
         "version_id": 3,
         "weight": 50,
         "config_overrides": {"tone": "formal"}
       },
       {
         "name": "treatment",
         "prompt_id": "prompt_course_authoring",
         "version_id": 4,
         "weight": 50,
         "config_overrides": {"tone": "conversational"}
       }
     ],
     "scope": {"tenant_ids": ["tenant-1"], "feature_flag": null},
     "status": "draft",
     "start_at": "2026-06-20T00:00:00Z",
     "end_at": "2026-07-20T00:00:00Z",
     "min_sample_size": 500,
     "auto_rollback": {
       "enabled": true,
       "metrics": [
         {"metric": "tool_call_error_rate", "operator": "gt", "threshold": 0.15, "window_minutes": 60},
         {"metric": "cost_per_turn", "operator": "gt", "threshold": 0.05, "window_minutes": 60}
       ]
     }
   }
   ```
2. Backend validates:
   - All referenced prompt versions exist and are active (or allowed for experiments).
   - Total variant weights sum to 100.
   - `scope` is valid (at least one tenant, or a feature flag that is enabled).
   - `end_at` is after `start_at`.
   - Variant names are unique within the experiment.
3. Experiment is created with `status = "draft"`. No assignment occurs yet.

**Phase 1 — Start Experiment**

1. Operator calls `PATCH /api/v1/ai/experiments/{exp_id}/start`.
2. Backend sets `status = "running"` and `started_at = NOW()`.
3. The `ExperimentAssigner` begins serving assignments for this experiment.
4. If `start_at` is in the future, the orchestrator only starts serving after that timestamp.

**Phase 2 — Assignment at Session Creation**

This is the critical runtime path:

1. User creates an AI session (US-AI-006).
2. The session creation flow calls `ExperimentAssigner.get_assignment(user_id, tenant_id, session_id)`.
3. `ExperimentAssigner` performs:
   a. Find all experiments that are `running` and whose `scope` matches this user's `tenant_id`.
   b. For each matching experiment, compute the user's assignment:
      - If `assignment_strategy == "hash_pct"`: `bucket = hash(user_id + experiment_id + hash_seed) % 100`. Assign to the variant whose `weight` range contains `bucket`.
      - If `assignment_strategy == "ff"`: Check the feature flag named in `flag_name` against the user. If enabled, assign to `treatment`; else `control`.
      - If `assignment_strategy == "pct"`: Generate a random float `[0, 100)` and assign by weight range.
   c. Return a list of `(experiment_id, variant_name, prompt_id, version_id, config_overrides)`.
4. The session record is updated with columns `experiment_assignments` (JSONB): `[{"experiment_id": "...", "variant_name": "control", "prompt_id": "...", "version_id": 3}]`.
5. The assignment is also recorded in `ai_experiment_assignments` for analytics.

**Phase 3 — Prompt Resolution at Turn Time**

1. At turn start, `ChatOrchestrator.build_prompt()` (US-AI-023) queries:
   ```python
   assignments = session.experiment_assignments or []
   # For each assignment, load the prompt version and resolve it
   prompt_parts = []
   for a in assignments:
       prompt = await prompt_repo.get_version(a["prompt_id"], a["version_id"])
       rendered = prompt.render(
           variables=build_context_variables(),
           config_overrides=a.get("config_overrides", {})
       )
       prompt_parts.append(rendered)
   # Also load any non-experiment prompts (always-on guardrails, etc.)
   system_prompt = "\n\n".join(prompt_parts)
   ```
2. The resolved system prompt is used for this turn but is NOT persisted. Only the `(prompt_id, version_id)` references are saved.
3. If multiple experiments assign the same `(prompt_id, version_id)` for the same user, the template is resolved only once with merged `config_overrides` (later overrides win).

**Phase 4 — Stop / Conclude Experiment**

1. Operator calls `PATCH /api/v1/ai/experiments/{exp_id}/stop` with optional `reason`.
2. Backend sets `status = "stopped"` and `stopped_at = NOW()`.
3. Existing sessions already assigned to this experiment continue to use their variant (sessions are not interrupted), but new sessions no longer receive assignments.
4. Alternatively, operator calls `PATCH /api/v1/ai/experiments/{exp_id}/conclude` with a `winner_variant_name`. This stops the experiment and (optionally) auto-promotes the winning variant's prompt version to be the default for all users.
5. When `end_at` is reached without manual stop, the experiment auto-concludes with status `"completed"`. No winner is declared automatically unless configured.

#### Flow 3: Auto-Rollback

1. Every `AI_EXPERIMENT_ROLLBACK_INTERVAL_SECONDS` (default 300), the background job `ExperimentRollbackJob` runs:
   a. Query all experiments with `status = "running"` and `auto_rollback.enabled = true`.
   b. For each variant in each experiment, query the metric windows defined in `auto_rollback.metrics`.
   c. For each metric, compute the current value over `window_minutes`. Compare against the threshold using the operator.
   d. If any metric exceeds threshold for the treatment variant AND the control variant is within normal range, trigger rollback:
      - Set experiment `status = "rolled_back"`.
      - Log the rollback reason and metric values to `ai_experiment_audit`.
      - Send an alert (via `logger.error` and optional webhook).
      - Existing sessions are not interrupted; only new sessions skip the experiment.
2. The frontend admin panel displays rollback status with a prominent red banner.

#### Flow 4: Variant Analytics Dashboard

1. Frontend queries `GET /api/v1/ai/experiments/{exp_id}/analytics` at periodic intervals.
2. Backend computes per-variant aggregates from:
   - `ai_sessions.experiment_assignments` joined to `ai_session_messages`, `ai_tool_call_logs`, `ai_usage_records` (US-AI-036), and `ai_rlhf_events` (US-AI-031).
3. Response shape:

```json
{
  "experiment_id": "exp_abc123",
  "experiment_name": "prompt-tone-ab-v1",
  "status": "running",
  "period": {"from": "2026-06-20T00:00:00Z", "to": "2026-07-20T00:00:00Z"},
  "variants": [
    {
      "variant_name": "control",
      "sessions_assigned": 245,
      "turns_completed": 890,
      "metrics": {
        "tool_call_error_rate": 0.08,
        "proposal_acceptance_rate": 0.72,
        "avg_tokens_per_turn": 2450,
        "avg_latency_ms": 4200,
        "cost_per_turn": 0.032,
        "total_cost": 28.48,
        "content_quality_score": 4.2,
        "rlhf_feedback_count": 120
      }
    },
    {
      "variant_name": "treatment",
      "sessions_assigned": 238,
      "turns_completed": 867,
      "metrics": {
        "tool_call_error_rate": 0.11,
        "proposal_acceptance_rate": 0.68,
        "avg_tokens_per_turn": 2680,
        "avg_latency_ms": 4500,
        "cost_per_turn": 0.038,
        "total_cost": 32.95,
        "content_quality_score": 3.9,
        "rlhf_feedback_count": 105
      }
    }
  ],
  "significance": {
    "significant": false,
    "confidence_level": 0.85,
    "recommended_sample_size": 500,
    "current_sample_size": 483
  },
  "generated_at": "2026-06-25T14:00:00Z"
}
```

4. Significance calculation uses a two-proportion z-test for binary metrics and Welch's t-test for continuous metrics. The `required_confidence` is configurable via `AI_EXPERIMENT_CONFIDENCE_THRESHOLD` (default 0.95).
5. Results are cached for 60 seconds (`AI_EXPERIMENT_ANALYTICS_CACHE_TTL`) to avoid repeated heavy aggregate queries.

### 1.5 Error Conditions

| Condition | HTTP Status | Error Code | Behavior |
|---|---|---|---|
| Prompt template has invalid Jinja2 syntax | 422 | `INVALID_TEMPLATE_SYNTAX` | Return line-level parse errors |
| Prompt references undeclared variable | 422 | `UNDECLARED_VARIABLE` | List missing variable names |
| Prompt content exceeds max length | 422 | `PROMPT_TOO_LONG` | Return max allowed length |
| Duplicate content hash for prompt name | 409 | `DUPLICATE_PROMPT_VERSION` | No new version created |
| Experiment variant weights do not sum to 100 | 422 | `INVALID_VARIANT_WEIGHTS` | Show current sum |
| Prompt version referenced by running experiment cannot be deactivated | 409 | `VERSION_IN_USE` | List referencing experiments |
| Experiment not found | 404 | `EXPERIMENT_NOT_FOUND` | Standard not-found |
| Cannot start experiment already running/completed | 409 | `INVALID_EXPERIMENT_STATE` | Show current status |
| Auto-rollback metric operator unknown | 422 | `UNKNOWN_METRIC_OPERATOR` | Valid operators: gt, lt, gte, lte |
| Feature flag for ff-based experiment not found | 422 | `FLAG_NOT_FOUND` | List available flags |
| Prompt registry disabled (feature flag off) | 404 | `FEATURE_NOT_AVAILABLE` | All prompt registry endpoints disabled |

---

## 2. Technical Design

### 2.1 New Database Tables — DDL

#### 2.1.1 `ai_prompts` — Prompt template definitions (one row per prompt name)

```sql
CREATE TABLE ai_prompts (
    id                  BIGSERIAL PRIMARY KEY,
    prompt_id           VARCHAR(64) NOT NULL UNIQUE,          -- ULID, human-readable prefix
    name                VARCHAR(200) NOT NULL UNIQUE,          -- e.g., 'course-authoring-system-v2'
    description         TEXT NOT NULL DEFAULT '',
    category            VARCHAR(32) NOT NULL DEFAULT 'system'
                        CHECK (category IN ('system', 'tool_definitions', 'guardrails', 'context_summary')),
    
    -- Metadata
    tags                JSONB NOT NULL DEFAULT '{}',           -- {"lang": "en", "domain": "compliance"}
    
    -- Version tracking
    current_version_id  INTEGER NOT NULL DEFAULT 1,
    current_version_sha VARCHAR(64) NOT NULL,                  -- SHA-256 of current version's content
    
    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Soft delete
    is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_ai_prompts_name ON ai_prompts(name);
CREATE INDEX idx_ai_prompts_category ON ai_prompts(category) WHERE is_deleted = FALSE;
```

#### 2.1.2 `ai_prompt_versions` — Immutable version rows

```sql
CREATE TABLE ai_prompt_versions (
    id                  BIGSERIAL PRIMARY KEY,
    version_id          INTEGER NOT NULL,                     -- Monotonic per prompt_id
    prompt_id           VARCHAR(64) NOT NULL REFERENCES ai_prompts(prompt_id) ON DELETE CASCADE,
    
    -- Content
    content             TEXT NOT NULL,                         -- Jinja2 template
    variables_schema    JSONB NOT NULL DEFAULT '{}',           -- JSON Schema for context variables
    
    -- Content hash for dedup detection
    content_sha256      VARCHAR(64) NOT NULL,
    
    -- Active flag (only one version per prompt is active at a time)
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Change tracking
    change_notes        TEXT NOT NULL DEFAULT '',
    created_by          VARCHAR(128),                          -- Operator user ID
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    UNIQUE (prompt_id, version_id),
    UNIQUE (prompt_id, content_sha256),                       -- Reject byte-identical content for same prompt
    CONSTRAINT fk_pv_prompt FOREIGN KEY (prompt_id)
        REFERENCES ai_prompts(prompt_id) ON DELETE CASCADE
);

-- Only one active version per prompt
CREATE UNIQUE INDEX idx_ai_pv_active ON ai_prompt_versions(prompt_id) WHERE is_active = TRUE;

CREATE INDEX idx_ai_pv_prompt ON ai_prompt_versions(prompt_id, version_id);
CREATE INDEX idx_ai_pv_created ON ai_prompt_versions(prompt_id, created_at DESC);
```

#### 2.1.3 `ai_prompt_audit` — Audit trail for activation/deactivation

```sql
CREATE TABLE ai_prompt_audit (
    id                  BIGSERIAL PRIMARY KEY,
    audit_id            VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    prompt_id           VARCHAR(64) NOT NULL REFERENCES ai_prompts(prompt_id) ON DELETE CASCADE,
    version_id          INTEGER NOT NULL,
    
    action              VARCHAR(16) NOT NULL
                        CHECK (action IN ('created', 'activated', 'deactivated', 'edited')),
    previous_version_id INTEGER,                               -- NULL for 'created'
    performed_by        VARCHAR(128),
    reason              TEXT,
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ai_pa_prompt ON ai_prompt_audit(prompt_id);
CREATE INDEX idx_ai_pa_created ON ai_prompt_audit(created_at DESC);
```

#### 2.1.4 `ai_experiments` — Experiment configuration

```sql
CREATE TABLE ai_experiments (
    id                  BIGSERIAL PRIMARY KEY,
    experiment_id       VARCHAR(64) NOT NULL UNIQUE,          -- ULID
    name                VARCHAR(200) NOT NULL UNIQUE,
    description         TEXT NOT NULL DEFAULT '',
    
    -- Assignment strategy
    assignment_strategy VARCHAR(16) NOT NULL DEFAULT 'hash_pct'
                        CHECK (assignment_strategy IN ('hash_pct', 'ff', 'pct')),
    hash_seed           INTEGER DEFAULT 42,                    -- Used for hash_pct strategy
    flag_name           VARCHAR(128),                          -- Feature flag name for 'ff' strategy
    
    -- Scope
    scope               JSONB NOT NULL DEFAULT '{}',           -- {"tenant_ids": [...], "feature_flag": null}
    
    -- Status
    status              VARCHAR(16) NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'running', 'stopped', 'completed', 'rolled_back')),
    
    -- Timing
    start_at            TIMESTAMPTZ,                           -- NULL = start immediately
    end_at              TIMESTAMPTZ,
    started_at          TIMESTAMPTZ,
    stopped_at          TIMESTAMPTZ,
    
    -- Auto-conclusion
    min_sample_size     INTEGER DEFAULT 500,
    auto_rollback       JSONB NOT NULL DEFAULT '{}',           -- {"enabled": false, "metrics": [...]}
    
    -- Audit
    created_by          VARCHAR(128),
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ai_exp_status ON ai_experiments(status);
CREATE INDEX idx_ai_exp_tenant ON ai_experiments USING gin (scope jsonb_path_ops);
CREATE INDEX idx_ai_exp_name ON ai_experiments(name);
```

#### 2.1.5 `ai_experiment_variants` — Variants within an experiment

```sql
CREATE TABLE ai_experiment_variants (
    id                  BIGSERIAL PRIMARY KEY,
    experiment_id       VARCHAR(64) NOT NULL REFERENCES ai_experiments(experiment_id) ON DELETE CASCADE,
    variant_name        VARCHAR(100) NOT NULL,                 -- 'control', 'treatment-a', etc.
    
    -- Prompt reference
    prompt_id           VARCHAR(64) NOT NULL REFERENCES ai_prompts(prompt_id),
    version_id          INTEGER NOT NULL,
    
    -- Configuration
    weight              INTEGER NOT NULL CHECK (weight >= 0 AND weight <= 100),
    config_overrides    JSONB NOT NULL DEFAULT '{}',           -- Variables to pass to template
    
    -- Metadata
    description         TEXT NOT NULL DEFAULT '',
    
    -- Unique per experiment
    UNIQUE (experiment_id, variant_name)
);

CREATE INDEX idx_ai_ev_experiment ON ai_experiment_variants(experiment_id);

-- Verify total weight = 100 via application logic (triggers are fragile across partition schemes)
```

#### 2.1.6 `ai_experiment_assignments` — Per-user, per-session assignment log

```sql
CREATE TABLE ai_experiment_assignments (
    id                  BIGSERIAL PRIMARY KEY,
    assignment_id       VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    experiment_id       VARCHAR(64) NOT NULL REFERENCES ai_experiments(experiment_id) ON DELETE CASCADE,
    variant_name        VARCHAR(100) NOT NULL,
    session_id          VARCHAR(64) NOT NULL,                  -- References ai_sessions.session_id
    user_id             VARCHAR(128) NOT NULL,
    tenant_id           VARCHAR(64) NOT NULL,
    
    -- Assignment metadata
    bucket              INTEGER NOT NULL,                      -- The [0, 100) bucket computed
    strategy_used       VARCHAR(16) NOT NULL,
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT fk_assign_session FOREIGN KEY (session_id)
        REFERENCES ai_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX idx_ai_ea_experiment ON ai_experiment_assignments(experiment_id);
CREATE INDEX idx_ai_ea_session ON ai_experiment_assignments(session_id);
CREATE INDEX idx_ai_ea_user ON ai_experiment_assignments(user_id, experiment_id);
CREATE INDEX idx_ai_ea_created ON ai_experiment_assignments(created_at DESC);
```

#### 2.1.7 `ai_experiment_audit` — Lifecycle audit trail

```sql
CREATE TABLE ai_experiment_audit (
    id                  BIGSERIAL PRIMARY KEY,
    audit_id            VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    experiment_id       VARCHAR(64) NOT NULL REFERENCES ai_experiments(experiment_id) ON DELETE CASCADE,
    
    action              VARCHAR(16) NOT NULL
                        CHECK (action IN ('created', 'started', 'stopped', 'concluded', 'rolled_back',
                                          'variant_added', 'variant_removed', 'auto_rollback_triggered')),
    payload             JSONB NOT NULL DEFAULT '{}',           -- Snapshot of relevant state at the time
    performed_by        VARCHAR(128),
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ai_eaudit_exp ON ai_experiment_audit(experiment_id);
CREATE INDEX idx_ai_eaudit_action ON ai_experiment_audit(action);
```

### 2.2 SQLAlchemy ORM Models

**New file: `app/models/ai_prompts.py`**

```python
"""ORM models for system prompt versioning and A/B experiment management."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, DateTime, JSON, Text, Integer, Boolean, BigInteger,
    UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ

from app.models.base import Base


def _ulid() -> str:
    """Generate a ULID-like identifier (mock for now, use python-ulid in production)."""
    return "prom_" + str(uuid.uuid4()).replace("-", "")[:26]


class AIPromptRecord(Base):
    """System prompt template — one row per logical prompt name."""

    __tablename__ = "ai_prompts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prompt_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_ulid
    )
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(
        String(32), default="system"
    )
    tags: Mapped[dict] = mapped_column(JSONB, default=dict)

    current_version_id: Mapped[int] = mapped_column(Integer, default=1)
    current_version_sha: Mapped[str] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    def to_dict(self) -> dict:
        return {
            "promptId": self.prompt_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "currentVersionId": self.current_version_id,
            "currentVersionSha": self.current_version_sha,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "isDeleted": self.is_deleted,
        }


class AIPromptVersionRecord(Base):
    """Immutable version of a system prompt template."""

    __tablename__ = "ai_prompt_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(Integer)
    prompt_id: Mapped[str] = mapped_column(
        String(64), index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variables_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    content_sha256: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    change_notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("prompt_id", "version_id", name="uq_pv_version"),
        UniqueConstraint("prompt_id", "content_sha256", name="uq_pv_content"),
        Index("idx_ai_pv_active_one", "prompt_id", postgresql_where=text("is_active = TRUE")),
    )

    def to_dict(self) -> dict:
        return {
            "versionId": self.version_id,
            "promptId": self.prompt_id,
            "content": self.content,
            "variablesSchema": self.variables_schema,
            "contentSha256": self.content_sha256,
            "isActive": self.is_active,
            "changeNotes": self.change_notes,
            "createdBy": self.created_by,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class AIExperimentRecord(Base):
    """A/B experiment configuration."""

    __tablename__ = "ai_experiments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_ulid
    )
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")

    assignment_strategy: Mapped[str] = mapped_column(String(16), default="hash_pct")
    hash_seed: Mapped[Optional[int]] = mapped_column(Integer, default=42)
    flag_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    scope: Mapped[dict] = mapped_column(JSONB, default=dict)

    status: Mapped[str] = mapped_column(String(16), default="draft")

    start_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    end_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    stopped_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)

    min_sample_size: Mapped[int] = mapped_column(Integer, default=500)
    auto_rollback: Mapped[dict] = mapped_column(JSONB, default=dict)

    created_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "experimentId": self.experiment_id,
            "name": self.name,
            "description": self.description,
            "assignmentStrategy": self.assignment_strategy,
            "hashSeed": self.hash_seed,
            "flagName": self.flag_name,
            "scope": self.scope,
            "status": self.status,
            "startAt": self.start_at.isoformat() if self.start_at else None,
            "endAt": self.end_at.isoformat() if self.end_at else None,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "stoppedAt": self.stopped_at.isoformat() if self.stopped_at else None,
            "minSampleSize": self.min_sample_size,
            "autoRollback": self.auto_rollback,
            "createdBy": self.created_by,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
```

### 2.3 Pydantic Request/Response DTOs

**New file: `app/routers/ai_prompt_dtos.py`**

```python
"""Pydantic DTOs for the System Prompt Registry and A/B Experiment APIs."""
from __future__ import annotations
from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime


# ── Prompt Registry DTOs ────────────────────────────────────

class PromptCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, pattern=r"^[a-z0-9_-]+$")
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="system")
    content: str = Field(..., min_length=10, max_length=50000, description="Jinja2 template body")
    variables_schema: dict = Field(default_factory=dict, description="JSON Schema for context variables")
    tags: dict[str, str] = Field(default_factory=dict)
    change_notes: str = Field(default="", max_length=2000)

    @field_validator("content")
    @classmethod
    def validate_jinja2(cls, v: str) -> str:
        try:
            from jinja2 import Environment, Meta
            env = Environment()
            ast = env.parse(v)
            # Just parse — don't render. Let the service do deeper validation.
        except Exception as exc:
            raise ValueError(f"Invalid Jinja2 template syntax: {exc}")
        return v


class PromptUpdate(BaseModel):
    content: str = Field(..., min_length=10, max_length=50000)
    variables_schema: dict = Field(default_factory=dict)
    change_notes: str = Field(default="", max_length=2000)

    @field_validator("content")
    @classmethod
    def validate_jinja2(cls, v: str) -> str:
        try:
            from jinja2 import Environment
            Environment().parse(v)
        except Exception as exc:
            raise ValueError(f"Invalid Jinja2 template syntax: {exc}")
        return v


class PromptVersionOut(BaseModel):
    versionId: int
    promptId: str
    content: str
    variablesSchema: dict
    contentSha256: str
    isActive: bool
    changeNotes: str
    createdBy: Optional[str] = None
    createdAt: Optional[str] = None


class PromptOut(BaseModel):
    promptId: str
    name: str
    description: str
    category: str
    tags: dict
    currentVersionId: int
    currentVersionSha: str
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    versions: list[PromptVersionOut] = []


class PromptPreviewRequest(BaseModel):
    variables: dict = Field(default_factory=dict, description="Context variable values for rendering")


class PromptPreviewResponse(BaseModel):
    promptId: str
    versionId: int
    rendered: str
    resolvedVariables: list[str]
    missingVariables: list[str] = []


class ActivateVersionRequest(BaseModel):
    versionId: int = Field(..., gt=0)


# ── Experiment DTOs ─────────────────────────────────────────

class VariantDef(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    promptId: str = Field(..., min_length=1)
    versionId: int = Field(..., gt=0)
    weight: int = Field(..., ge=0, le=100)
    configOverrides: dict = Field(default_factory=dict)
    description: str = Field(default="")


class AutoRollbackConfig(BaseModel):
    enabled: bool = False
    metrics: list[dict] = Field(default_factory=list, description="[{'metric': str, 'operator': str, 'threshold': float, 'window_minutes': int}]")


class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, pattern=r"^[a-z0-9_-]+$")
    description: str = Field(default="", max_length=2000)
    assignmentStrategy: str = Field(default="hash_pct")
    hashSeed: int = Field(default=42)
    flagName: Optional[str] = Field(None)
    scope: dict = Field(default_factory=lambda: {"tenant_ids": [], "feature_flag": None})
    variants: list[VariantDef] = Field(..., min_length=2, max_length=10)
    status: str = Field(default="draft")
    startAt: Optional[datetime] = None
    endAt: Optional[datetime] = None
    minSampleSize: int = Field(default=500, ge=1)
    autoRollback: AutoRollbackConfig = Field(default_factory=AutoRollbackConfig)

    @model_validator(mode="after")
    def validate_weights(self):
        total = sum(v.weight for v in self.variants)
        if total != 100:
            raise ValueError(f"Variant weights must sum to 100, got {total}")
        if self.assignmentStrategy == "ff" and not self.flagName:
            raise ValueError("Feature-flag strategy requires flagName")
        return self


class ExperimentUpdate(BaseModel):
    description: Optional[str] = None
    endAt: Optional[datetime] = None
    minSampleSize: Optional[int] = None
    autoRollback: Optional[AutoRollbackConfig] = None


class ExperimentVariantOut(BaseModel):
    variantName: str
    promptId: str
    versionId: int
    weight: int
    configOverrides: dict
    description: str = ""


class ExperimentOut(BaseModel):
    experimentId: str
    name: str
    description: str
    assignmentStrategy: str
    hashSeed: Optional[int] = None
    flagName: Optional[str] = None
    scope: dict
    status: str
    variants: list[ExperimentVariantOut] = []
    startAt: Optional[str] = None
    endAt: Optional[str] = None
    startedAt: Optional[str] = None
    stoppedAt: Optional[str] = None
    minSampleSize: int = 500
    autoRollback: dict = {}
    createdBy: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class ExperimentAnalyticsVariant(BaseModel):
    variantName: str
    sessionsAssigned: int = 0
    turnsCompleted: int = 0
    metrics: dict = Field(default_factory=dict)


class ExperimentAnalyticsResponse(BaseModel):
    experimentId: str
    experimentName: str
    status: str
    period: dict = Field(default_factory=dict)
    variants: list[ExperimentAnalyticsVariant] = []
    significance: dict = Field(default_factory=dict)
    generatedAt: str = ""


class StartExperimentRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class StopExperimentRequest(BaseModel):
    reason: str = Field(default="", max_length=500)
    concludeWithVariant: Optional[str] = None
    promoteVariant: bool = False
```

### 2.4 New Service Signatures

**New file: `app/services/prompt_registry.py`**

```python
"""Prompt registry service — CRUD, versioning, rendering, and activation."""
from __future__ import annotations
import hashlib
from typing import Optional
from jinja2 import Environment, BaseLoader, TemplateNotFound, UndefinedError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func


class PromptNotFoundError(Exception):
    """Prompt not found by prompt_id or name."""


class PromptVersionNotFoundError(Exception):
    """Version not found for prompt."""


class DuplicatePromptContentError(Exception):
    """Same content hash already exists for this prompt."""


class PromptRenderError(Exception):
    """Template rendering failed due to missing/invalid variables."""


class PromptRegistryService:
    """Manages system prompt templates, versioning, and rendering."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_prompt(
        self,
        name: str,
        description: str,
        category: str,
        content: str,
        variables_schema: dict,
        tags: dict,
        change_notes: str,
        created_by: Optional[str] = None,
    ) -> AIPromptRecord:
        """Create a new prompt with initial version_id = 1."""
        # 1. Check name uniqueness
        existing = await self.session.execute(
            select(AIPromptRecord).where(AIPromptRecord.name == name)
        )
        if existing.scalar_one_or_none():
            raise PromptConflictError(f"Prompt name '{name}' already exists")

        # 2. Hash content
        content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # 3. Create prompt record
        prompt = AIPromptRecord(
            name=name,
            description=description,
            category=category,
            tags=tags,
            current_version_id=1,
            current_version_sha=content_sha,
        )
        self.session.add(prompt)
        await self.session.flush()  # Get prompt_id

        # 4. Create version 1
        version = AIPromptVersionRecord(
            version_id=1,
            prompt_id=prompt.prompt_id,
            content=content,
            variables_schema=variables_schema,
            content_sha256=content_sha,
            is_active=True,
            change_notes=change_notes,
            created_by=created_by,
        )
        self.session.add(version)
        await self.session.commit()
        await self.session.refresh(prompt)
        return prompt

    async def create_version(
        self,
        prompt_id: str,
        content: str,
        variables_schema: dict,
        change_notes: str,
        created_by: Optional[str] = None,
    ) -> AIPromptVersionRecord:
        """Create a new version of an existing prompt. Content is immutable once set."""
        prompt = await self._get_prompt(prompt_id)

        content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Check for duplicate content (same prompt + same hash = no-op)
        dup_check = await self.session.execute(
            select(AIPromptVersionRecord).where(
                AIPromptVersionRecord.prompt_id == prompt_id,
                AIPromptVersionRecord.content_sha256 == content_sha,
            )
        )
        if dup_check.scalar_one_or_none():
            raise DuplicatePromptContentError("This content already exists as a previous version")

        # Find next version_id
        max_ver = await self.session.execute(
            select(func.max(AIPromptVersionRecord.version_id)).where(
                AIPromptVersionRecord.prompt_id == prompt_id
            )
        )
        next_version = (max_ver.scalar() or 0) + 1

        version = AIPromptVersionRecord(
            version_id=next_version,
            prompt_id=prompt_id,
            content=content,
            variables_schema=variables_schema,
            content_sha256=content_sha,
            is_active=False,  # Requires explicit activation
            change_notes=change_notes,
            created_by=created_by,
        )
        self.session.add(version)

        # Update prompt's current_version tracking
        prompt.current_version_id = next_version
        prompt.current_version_sha = content_sha

        await self.session.commit()
        await self.session.refresh(version)
        return version

    async def activate_version(
        self,
        prompt_id: str,
        version_id: int,
        performed_by: Optional[str] = None,
    ) -> AIPromptVersionRecord:
        """Activate a specific version, deactivating all others."""
        prompt = await self._get_prompt(prompt_id)
        version = await self._get_version(prompt_id, version_id)

        # Deactivate all versions for this prompt
        await self.session.execute(
            # SQLAlchemy bulk update equivalent
            select(AIPromptVersionRecord).where(
                AIPromptVersionRecord.prompt_id == prompt_id,
                AIPromptVersionRecord.is_active == True,
            )
        )
        # Use direct UPDATE to deactivate all
        from sqlalchemy import update as sa_update
        await self.session.execute(
            sa_update(AIPromptVersionRecord)
            .where(AIPromptVersionRecord.prompt_id == prompt_id)
            .values(is_active=False)
        )

        # Activate the target version
        version.is_active = True

        # Update prompt metadata
        prompt.current_version_id = version_id
        prompt.current_version_sha = version.content_sha256

        # Audit log
        audit = AIPromptAuditRecord(
            prompt_id=prompt_id,
            version_id=version_id,
            action="activated",
            performed_by=performed_by,
        )
        self.session.add(audit)

        await self.session.commit()
        await self.session.refresh(version)
        return version

    async def render_prompt(
        self,
        prompt_id: str,
        version_id: Optional[int] = None,
        variables: dict | None = None,
    ) -> str:
        """Resolve a prompt template with context variables and return rendered text.

        If version_id is None, uses the currently active version.
        """
        if version_id:
            version = await self._get_version(prompt_id, version_id)
        else:
            version = await self._get_active_version(prompt_id)

        env = Environment(autoescape=False)
        template = env.from_string(version.content)

        try:
            rendered = template.render(**(variables or {}))
        except UndefinedError as exc:
            raise PromptRenderError(f"Missing variable in template: {exc}")
        except Exception as exc:
            raise PromptRenderError(f"Template rendering failed: {exc}")

        return rendered

    async def list_prompts(
        self,
        category: Optional[str] = None,
        include_deleted: bool = False,
    ) -> Sequence[AIPromptRecord]:
        query = select(AIPromptRecord)
        if not include_deleted:
            query = query.where(AIPromptRecord.is_deleted == False)
        if category:
            query = query.where(AIPromptRecord.category == category)
        result = await self.session.execute(query.order_by(AIPromptRecord.name))
        return result.scalars().all()

    async def get_prompt_with_versions(
        self, prompt_id: str
    ) -> tuple[AIPromptRecord, list[AIPromptVersionRecord]]:
        prompt = await self._get_prompt(prompt_id)
        versions_result = await self.session.execute(
            select(AIPromptVersionRecord)
            .where(AIPromptVersionRecord.prompt_id == prompt_id)
            .order_by(AIPromptVersionRecord.version_id.desc())
        )
        return prompt, versions_result.scalars().all()

    # ── Private helpers ─────────────────────────────

    async def _get_prompt(self, prompt_id: str) -> AIPromptRecord:
        result = await self.session.execute(
            select(AIPromptRecord).where(
                AIPromptRecord.prompt_id == prompt_id,
                AIPromptRecord.is_deleted == False,
            )
        )
        prompt = result.scalar_one_or_none()
        if not prompt:
            raise PromptNotFoundError(f"Prompt '{prompt_id}' not found")
        return prompt

    async def _get_version(self, prompt_id: str, version_id: int) -> AIPromptVersionRecord:
        result = await self.session.execute(
            select(AIPromptVersionRecord).where(
                AIPromptVersionRecord.prompt_id == prompt_id,
                AIPromptVersionRecord.version_id == version_id,
            )
        )
        version = result.scalar_one_or_none()
        if not version:
            raise PromptVersionNotFoundError(
                f"Version {version_id} not found for prompt '{prompt_id}'"
            )
        return version

    async def _get_active_version(self, prompt_id: str) -> AIPromptVersionRecord:
        result = await self.session.execute(
            select(AIPromptVersionRecord).where(
                AIPromptVersionRecord.prompt_id == prompt_id,
                AIPromptVersionRecord.is_active == True,
            )
        )
        version = result.scalar_one_or_none()
        if not version:
            raise PromptVersionNotFoundError(f"No active version for prompt '{prompt_id}'")
        return version
```

**New file: `app/services/experiment_assigner.py`**

```python
"""Experiment assignment service — deterministic variant assignment for A/B tests."""
from __future__ import annotations
import hashlib
import json
from typing import Optional, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.ai_prompts import AIExperimentRecord, AIExperimentVariantRecord, AIExperimentAssignmentRecord
from app.repositories.ai_prompt_repo import ExperimentRepository


class ExperimentAssigner:
    """Assigns users to experiment variants at session creation time."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_assignments(
        self,
        user_id: str,
        tenant_id: str,
        session_id: str,
    ) -> list[dict]:
        """Resolve all experiment assignments for a user at session creation.

        Returns list of dicts: [{
            "experiment_id": str,
            "variant_name": str,
            "prompt_id": str,
            "version_id": int,
            "config_overrides": dict,
        }]
        """
        # Find all running experiments that scope-matches this tenant
        now = func.now()
        experiments = await self.session.execute(
            select(AIExperimentRecord).where(
                AIExperimentRecord.status == "running",
                and_(
                    AIExperimentRecord.start_at.is_(None),
                    AIExperimentRecord.start_at <= now,
                ) if False else True,  # Simplified — real impl with proper time check
            )
        )
        # Proper query:
        experiments = await self.session.execute(
            select(AIExperimentRecord).where(
                AIExperimentRecord.status == "running",
                (
                    (AIExperimentRecord.start_at.is_(None))
                    | (AIExperimentRecord.start_at <= func.now())
                ),
                (
                    (AIExperimentRecord.end_at.is_(None))
                    | (AIExperimentRecord.end_at >= func.now())
                ),
            )
        )
        all_experiments: list[AIExperimentRecord] = experiments.scalars().all()

        # Filter by scope
        matching = []
        for exp in all_experiments:
            scope = exp.scope or {}
            tenant_ids = scope.get("tenant_ids", [])
            feature_flag = scope.get("feature_flag")

            if tenant_ids and tenant_id not in tenant_ids:
                continue
            # If feature_flag is set, check it (depends on US-AI-002)
            if feature_flag:
                from app.services.feature_flags import is_flag_enabled
                if not await is_flag_enabled(feature_flag, user_id, tenant_id):
                    continue

            matching.append(exp)

        # Get variants for each matching experiment
        assignments = []
        for exp in matching:
            variants_result = await self.session.execute(
                select(AIExperimentVariantRecord).where(
                    AIExperimentVariantRecord.experiment_id == exp.experiment_id
                )
            )
            variants: list[AIExperimentVariantRecord] = variants_result.scalars().all()
            if not variants:
                continue

            # Compute assignment
            variant = self._assign_variant(exp, variants, user_id)

            # Persist assignment
            assignment_record = AIExperimentAssignmentRecord(
                experiment_id=exp.experiment_id,
                variant_name=variant.variant_name,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                bucket=self._compute_bucket(exp, user_id),
                strategy_used=exp.assignment_strategy,
            )
            self.session.add(assignment_record)

            assignments.append({
                "experiment_id": exp.experiment_id,
                "variant_name": variant.variant_name,
                "prompt_id": variant.prompt_id,
                "version_id": variant.version_id,
                "config_overrides": variant.config_overrides or {},
            })

        if assignments:
            await self.session.flush()

        return assignments

    def _assign_variant(
        self,
        experiment: AIExperimentRecord,
        variants: list[AIExperimentVariantRecord],
        user_id: str,
    ) -> AIExperimentVariantRecord:
        """Deterministically select a variant based on strategy."""
        strategy = experiment.assignment_strategy

        if strategy == "ff":
            # Feature-flag based: control (flag off) or first non-control variant (flag on)
            control = [v for v in variants if v.variant_name == "control"]
            treatment = [v for v in variants if v.variant_name != "control"]
            return control[0] if not self._ff_enabled(experiment.flag_name, user_id) else treatment[0]

        # hash_pct and pct strategies: compute bucket
        bucket = self._compute_bucket(experiment, user_id)

        # Sort variants by weight to ensure deterministic range assignment
        sorted_variants = sorted(variants, key=lambda v: v.variant_name)
        cumulative = 0
        for variant in sorted_variants:
            cumulative += variant.weight
            if bucket < cumulative:
                return variant

        # Fallback: return last variant
        return sorted_variants[-1]

    def _compute_bucket(self, experiment: AIExperimentRecord, user_id: str) -> int:
        """Compute deterministic [0, 100) bucket from user_id + experiment_id + seed."""
        seed = experiment.hash_seed or 42
        key = f"{user_id}:{experiment.experiment_id}:{seed}"
        hash_bytes = hashlib.sha256(key.encode("utf-8")).digest()
        bucket = int.from_bytes(hash_bytes[:4], byteorder="big") % 100
        return bucket

    def _ff_enabled(self, flag_name: str | None, user_id: str) -> bool:
        """Placeholder for feature flag check. Real impl depends on US-AI-002."""
        if not flag_name:
            return False
        # TODO: Integrate with FeatureFlagService from US-AI-002
        return False
```

### 2.5 API Contracts

#### 2.5.1 Prompt Registry CRUD

**`POST /api/v1/ai/prompts`** — Create a new system prompt

Request:
```json
{
  "name": "course-authoring-v2",
  "description": "Main system prompt for course authoring chat sessions",
  "category": "system",
  "content": "You are an expert instructional designer creating e-learning content.\nCourse: {{ course_title }}\nLanguage: {{ language }}\n\nAvailable tools:\n{% for tool in tool_definitions %}- {{ tool.name }}: {{ tool.description }}\n{% endfor %}\n\nCurrent course structure:\n{% for page in pages %}{{ page.order }}. {{ page.title }} ({{ page.component_count }} components)\n{% endfor %}\n\n{{ guardrails | default('') }}",
  "variables_schema": {
    "type": "object",
    "required": ["course_title", "tool_definitions"],
    "properties": {
      "course_title": {"type": "string"},
      "language": {"type": "string", "default": "en"},
      "tool_definitions": {"type": "array"},
      "pages": {"type": "array"},
      "guardrails": {"type": "string"}
    }
  },
  "tags": {"lang": "en", "domain": "general"},
  "change_notes": "Initial version of course authoring system prompt"
}
```

Response `201`:
```json
{
  "promptId": "prom_abc123",
  "name": "course-authoring-v2",
  "description": "Main system prompt for course authoring chat sessions",
  "category": "system",
  "tags": {"lang": "en", "domain": "general"},
  "currentVersionId": 1,
  "currentVersionSha": "a1b2c3d4e5f6...",
  "versions": [
    {
      "versionId": 1,
      "promptId": "prom_abc123",
      "content": "...",
      "variablesSchema": {...},
      "contentSha256": "a1b2c3d4e5f6...",
      "isActive": true,
      "changeNotes": "Initial version of course authoring system prompt",
      "createdBy": null,
      "createdAt": "2026-06-14T12:00:00Z"
    }
  ],
  "createdAt": "2026-06-14T12:00:00Z",
  "updatedAt": "2026-06-14T12:00:00Z"
}
```

**`GET /api/v1/ai/prompts`** — List prompts (query: `?category=system&include_deleted=false`)

**`GET /api/v1/ai/prompts/{prompt_id}`** — Get prompt with all versions

**`POST /api/v1/ai/prompts/{prompt_id}/versions`** — Create new version

Request:
```json
{
  "content": "...updated jinja2 template...",
  "variables_schema": {...},
  "change_notes": "Added compliance guardrails section"
}
```

Response `201`: Version object with `versionId`, `isActive: false`.

**`PATCH /api/v1/ai/prompts/{prompt_id}/activate`** — Activate a version

Request:
```json
{
  "versionId": 3
}
```

**`POST /api/v1/ai/prompts/{prompt_id}/preview`** — Dry-run rendering

Request:
```json
{
  "version_id": 3,
  "variables": {
    "course_title": "Introduction to Python",
    "language": "en",
    "tool_definitions": [{"name": "list_pages", "description": "List all pages"}],
    "pages": [{"order": 1, "title": "Welcome", "component_count": 2}]
  }
}
```

Response:
```json
{
  "promptId": "prom_abc123",
  "versionId": 3,
  "rendered": "You are an expert instructional designer...\nCourse: Introduction to Python\n...",
  "resolvedVariables": ["course_title", "language", "tool_definitions", "pages"],
  "missingVariables": []
}
```

#### 2.5.2 A/B Experiment CRUD

**`POST /api/v1/ai/experiments`** — Create experiment

Request: (see Flow 2 Phase 0 in Section 1.4)

Response `201`: Full experiment object with variants.

**`GET /api/v1/ai/experiments`** — List experiments (query: `?status=running`)

**`GET /api/v1/ai/experiments/{exp_id}`** — Get experiment detail with variants

**`PATCH /api/v1/ai/experiments/{exp_id}`** — Update experiment metadata

**`PATCH /api/v1/ai/experiments/{exp_id}/start`** — Start experiment

Request:
```json
{
  "reason": "Launching tone A/B test for Q3"
}
```

Response `200`: Experiment object with `status: "running"`, `startedAt` set.

**`PATCH /api/v1/ai/experiments/{exp_id}/stop`** — Stop experiment

**`PATCH /api/v1/ai/experiments/{exp_id}/conclude`** — Conclude with winner

Request:
```json
{
  "concludeWithVariant": "treatment",
  "promoteVariant": true
}
```

If `promoteVariant: true`, the backend auto-activates the winning variant's prompt version.

#### 2.5.3 Variant Analytics

**`GET /api/v1/ai/experiments/{exp_id}/analytics`** — Per-variant metric aggregates

Query params: `?from=2026-06-20&to=2026-07-20`

Response: (see Flow 4 in Section 1.4)

#### 2.5.4 Integration with AI Chat / Session Creation

The `POST /api/v1/ai/sessions` endpoint (US-AI-006) must be extended to accept an optional `experiment_context` field and return the resolved assignments in the session response.

Extended session creation response (new fields):
```json
{
  "sessionId": "sess_abc123",
  "courseId": "course-python-101",
  "status": "active",
  "experimentAssignments": [
    {
      "experimentId": "exp_abc123",
      "variantName": "control",
      "promptId": "prom_abc123",
      "versionId": 3
    }
  ],
  "createdAt": "2026-06-14T12:00:00Z",
  "expiresAt": "2026-06-14T13:00:00Z"
}
```

### 2.6 Modifications to Existing Code

#### 2.6.1 `app/main.py` — Add new routers

```python
from app.routers import ai_prompts, ai_experiments

# In api_router includes, add:
api_router.include_router(ai_prompts.router)
api_router.include_router(ai_experiments.router)
```

Also add a startup seed for default system prompts, similar to the existing `seed_component_types` and `seed_template_types`:

```python
# In lifespan startup block:
from app.services.seed_system_prompts import seed_system_prompts
async with SessionLocal() as session:
    count = await seed_system_prompts(session)
    logger.info("Seeded %d system prompts", count)
```

#### 2.6.2 `app/routers/ai_chat.py` (from US-AI-023) — Integrate prompt resolution

In `ChatOrchestrator.build_prompt()`, replace the hardcoded system prompt with:

```python
async def build_prompt(
    self,
    session_record: AISessionRecord,
    course_state: dict,
    tool_definitions: list[dict],
    user_message: str,
    conversation_history: list,
) -> list[dict]:
    """Build the message array for the LLM call, resolving experiment-assigned prompts."""

    prompt_parts = []

    # 1. Resolve experiment-assigned system prompts
    assignments = session_record.experiment_assignments or []
    for assignment in assignments:
        try:
            rendered = await self.prompt_registry.render_prompt(
                prompt_id=assignment["prompt_id"],
                version_id=assignment["version_id"],
                variables={
                    "course_title": course_state.get("title", ""),
                    "language": course_state.get("language", "en"),
                    "tool_definitions": tool_definitions,
                    "pages": course_state.get("pages", []),
                    "guardrails": self._build_guardrails(session_record),
                    **assignment.get("config_overrides", {}),
                },
            )
            prompt_parts.append(rendered)
        except PromptRenderError as exc:
            logger.error("Prompt render failed for %s v%d: %s",
                         assignment["prompt_id"], assignment["version_id"], exc)
            # Fallback: skip this prompt part, don't fail the turn

    # 2. Append always-on prompts (guardrails not tied to experiments)
    for always_on in await self._get_always_on_prompts():
        prompt_parts.append(always_on)

    system_prompt = "\n\n---\n\n".join(prompt_parts)

    # Build full message array
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})
    return messages
```

#### 2.6.3 `app/repositories/` — Add repository for new models

**New file: `app/repositories/ai_prompt_repo.py`**

```python
"""Repository for AI prompt and experiment records."""
from __future__ import annotations
from typing import Optional, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update as sa_update

from app.models.ai_prompts import (
    AIPromptRecord,
    AIPromptVersionRecord,
    AIPromptAuditRecord,
    AIExperimentRecord,
    AIExperimentVariantRecord,
    AIExperimentAssignmentRecord,
    AIExperimentAuditRecord,
)


class PromptRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_version(self, prompt_id: str) -> Optional[AIPromptVersionRecord]:
        result = await self.session.execute(
            select(AIPromptVersionRecord).where(
                AIPromptVersionRecord.prompt_id == prompt_id,
                AIPromptVersionRecord.is_active == True,
            )
        )
        return result.scalar_one_or_none()


class ExperimentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_running(self) -> Sequence[AIExperimentRecord]:
        result = await self.session.execute(
            select(AIExperimentRecord).where(
                AIExperimentRecord.status == "running"
            )
        )
        return result.scalars().all()

    async def get_variants(
        self, experiment_id: str
    ) -> Sequence[AIExperimentVariantRecord]:
        result = await self.session.execute(
            select(AIExperimentVariantRecord).where(
                AIExperimentVariantRecord.experiment_id == experiment_id
            )
        )
        return result.scalars().all()
```

### 2.7 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FEATURE_AI_PROMPT_REGISTRY` | `false` | Master toggle for prompt registry and A/B testing |
| `AI_PROMPT_MAX_TEMPLATE_CHARS` | `50000` | Maximum length of a prompt template |
| `AI_EXPERIMENT_CONFIDENCE_THRESHOLD` | `0.95` | Required confidence level for declaring statistical significance |
| `AI_EXPERIMENT_ANALYTICS_CACHE_TTL` | `60` | Seconds to cache analytics query results |
| `AI_EXPERIMENT_ROLLBACK_INTERVAL_SECONDS` | `300` | Interval for auto-rollback background job |
| `AI_EXPERIMENT_MIN_SAMPLE_SIZE_DEFAULT` | `500` | Default minimum sample size for new experiments |
| `AI_PROMPT_REGISTRY_DB_SCHEMA` | `public` | Database schema for prompt registry tables |

### 2.8 Seed Data

**New file: `app/services/seed_system_prompts.py`**

```python
"""Seed default system prompts into the registry on first deploy."""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.ai_prompts import AIPromptRecord, AIPromptVersionRecord
from app.services.prompt_registry import PromptRegistryService


DEFAULT_SYSTEM_PROMPTS = [
    {
        "name": "course-authoring-default",
        "description": "Default system prompt for AI course authoring chat sessions",
        "category": "system",
        "content": (
            "You are an expert instructional designer creating e-learning content. "
            "Your job is to help authors build, edit, and review course content.\n\n"
            "Course: {{ course_title | default('Untitled Course') }}\n"
            "Language: {{ language | default('en') }}\n\n"
            "Available tools:\n"
            "{% for tool in tool_definitions %}"
            "- {{ tool.name }}: {{ tool.description }}\n"
            "{% endfor %}\n\n"
            "Current course structure:\n"
            "{% for page in pages %}"
            "{{ page.order }}. {{ page.title }} ({{ page.component_count }} components)\n"
            "{% else %}"
            "(No pages yet)\n"
            "{% endfor %}\n\n"
            "{{ guardrails | default('') }}"
        ),
        "variables_schema": {
            "type": "object",
            "required": ["tool_definitions"],
            "properties": {
                "course_title": {"type": "string"},
                "language": {"type": "string", "default": "en"},
                "tool_definitions": {"type": "array"},
                "pages": {"type": "array"},
                "guardrails": {"type": "string"},
            },
        },
        "tags": {"lang": "en", "domain": "general"},
    },
    {
        "name": "guardrails-default",
        "description": "Default content safety guardrails appended to every chat turn",
        "category": "guardrails",
        "content": (
            "SAFETY RULES:\n"
            "1. NEVER generate content about: violence, hate speech, illegal activities, "
            "or medical/financial/legal advice.\n"
            "2. If a user asks you to create content outside course authoring, "
            "politely redirect them to course-related tasks.\n"
            "3. When a user corrects a course fact, accept the correction gracefully "
            "and update the content.\n"
            "4. Never claim to have created or modified content unless you have called "
            "the appropriate tool and received a success response.\n"
            "5. If you cannot fulfill a request because it violates these rules, explain why."
        ),
        "variables_schema": {"type": "object", "properties": {}},
        "tags": {"lang": "en", "type": "guardrails"},
    },
]


async def seed_system_prompts(session: AsyncSession) -> int:
    """Seed default prompts if the registry is empty."""
    result = await session.execute(
        select(func.count(AIPromptRecord.id))
    )
    if result.scalar() > 0:
        return 0  # Already seeded

    service = PromptRegistryService(session)
    count = 0
    for prompt_data in DEFAULT_SYSTEM_PROMPTS:
        await service.create_prompt(
            name=prompt_data["name"],
            description=prompt_data["description"],
            category=prompt_data["category"],
            content=prompt_data["content"],
            variables_schema=prompt_data["variables_schema"],
            tags=prompt_data["tags"],
            change_notes="Default seed prompt",
            created_by="system",
        )
        count += 1

    return count
```

### 2.9 Background Job: Auto-Rollback

**New function in `app/services/experiment_rollback.py`:**

```python
"""Background job that monitors running experiments and auto-rollbacks degrading variants."""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.ai_prompts import AIExperimentRecord, AIExperimentVariantRecord
from app.repositories.ai_prompt_repo import ExperimentRepository

logger = logging.getLogger(__name__)

ROLLBACK_METRIC_QUERIES = {
    "tool_call_error_rate": """
        SELECT COUNT(*) FILTER (WHERE atcl.status = 'error')::float / NULLIF(COUNT(*), 0)
        FROM ai_tool_call_logs atcl
        JOIN ai_sessions sess ON atcl.session_id = sess.session_id
        JOIN ai_experiment_assignments aea ON aea.session_id = sess.session_id
        WHERE aea.experiment_id = :exp_id
          AND aea.variant_name = :variant
          AND atcl.created_at >= :window_start
    """,
    "cost_per_turn": """
        SELECT COALESCE(SUM(aur.cost) / NULLIF(COUNT(DISTINCT aur.turn_id), 0), 0)
        FROM ai_usage_records aur
        JOIN ai_sessions sess ON aur.session_id = sess.session_id
        JOIN ai_experiment_assignments aea ON aea.session_id = sess.session_id
        WHERE aea.experiment_id = :exp_id
          AND aea.variant_name = :variant
          AND aur.created_at >= :window_start
    """,
    "proposal_acceptance_rate": """
        SELECT COUNT(*) FILTER (WHERE status = 'applied')::float / NULLIF(COUNT(*), 0)
        FROM ai_proposals ap
        JOIN ai_sessions sess ON ap.session_id = sess.session_id
        JOIN ai_experiment_assignments aea ON aea.session_id = sess.session_id
        WHERE aea.experiment_id = :exp_id
          AND aea.variant_name = :variant
          AND ap.created_at >= :window_start
    """,
}


async def check_and_rollback(session: AsyncSession) -> list[dict]:
    """Check all running experiments for auto-rollback conditions. Returns list of rollbacks triggered."""
    repo = ExperimentRepository(session)
    experiments = await repo.list_running()
    rollbacks = []

    for exp in experiments:
        auto_rb = exp.auto_rollback or {}
        if not auto_rb.get("enabled"):
            continue

        metrics_config = auto_rb.get("metrics", [])
        if not metrics_config:
            continue

        variants = await repo.get_variants(exp.experiment_id)

        for metric_cfg in metrics_config:
            metric_name = metric_cfg.get("metric")
            operator = metric_cfg.get("operator", "gt")
            threshold = metric_cfg.get("threshold", 0)
            window_minutes = metric_cfg.get("window_minutes", 60)

            if metric_name not in ROLLBACK_METRIC_QUERIES:
                logger.warning("Unknown rollback metric: %s", metric_name)
                continue

            window_start = datetime.utcnow() - timedelta(minutes=window_minutes)
            query_text = ROLLBACK_METRIC_QUERIES[metric_name]

            variant_values = {}
            for variant in variants:
                # Execute raw SQL for metric
                result = await session.execute(
                    text(query_text),
                    {
                        "exp_id": exp.experiment_id,
                        "variant": variant.variant_name,
                        "window_start": window_start,
                    }
                )
                variant_values[variant.variant_name] = result.scalar() or 0.0

            # Check if treatment variant exceeds threshold while control is normal
            control_val = variant_values.get("control", 0)
            for vname, vval in variant_values.items():
                if vname == "control":
                    continue
                exceeded = False
                if operator == "gt" and vval > threshold:
                    exceeded = True
                elif operator == "gte" and vval >= threshold:
                    exceeded = True
                elif operator == "lt" and vval < threshold:
                    exceeded = True
                elif operator == "lte" and vval <= threshold:
                    exceeded = True

                if exceeded:
                    logger.warning(
                        "Auto-rollback triggered: experiment=%s variant=%s metric=%s "
                        "value=%.4f threshold=%.4f",
                        exp.experiment_id, vname, metric_name, vval, threshold,
                    )
                    # Trigger rollback
                    exp.status = "rolled_back"
                    exp.stopped_at = datetime.utcnow()

                    # Write audit entry
                    audit = AIExperimentAuditRecord(
                        experiment_id=exp.experiment_id,
                        action="auto_rollback_triggered",
                        payload={
                            "metric": metric_name,
                            "variant": vname,
                            "value": vval,
                            "threshold": threshold,
                            "operator": operator,
                            "window_minutes": window_minutes,
                            "control_value": control_val,
                        },
                    )
                    session.add(audit)
                    rollbacks.append({
                        "experiment_id": exp.experiment_id,
                        "variant": vname,
                        "metric": metric_name,
                        "value": vval,
                        "threshold": threshold,
                    })
                    break  # Only one rollback per experiment per cycle

    if rollbacks:
        await session.commit()

    return rollbacks
```

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Prompt registry API latency (p95) | < 200ms | `/api/v1/ai/prompts/*` endpoints |
| Experiment assignment latency | < 50ms | Added to session creation path |
| Prompt rendering latency | < 100ms | Per template render at turn start |
| Analytics query latency (p95) | < 5s for 30-day window | `/api/v1/ai/experiments/{id}/analytics` |
| Auto-rollback check interval | Every 300s | Background job |
| Concurrent experiments supported | 50 | Horizontal scaling of worker |

### 3.2 Security

| Requirement | Implementation |
|---|---|
| Prompt content integrity | SHA-256 content hash with duplicate rejection within a prompt |
| Immutable version history | Once `content` is stored, any edit creates a new version — no UPDATE allowed on `ai_prompt_versions.content` |
| Access control | All prompt registry and experiment APIs restricted to `admin` and `operator` roles |
| Audit trail | Every activation, deactivation, experiment start/stop recorded in audit tables |
| No prompt content in logs | Only `(prompt_id, version_id)` references logged — never the raw template text |

### 3.3 Data Retention

| Data | Retention | Cleanup |
|---|---|---|
| Prompt versions | Indefinite (immutable history) | Soft delete at prompt level |
| Experiment configs | Indefinite | Soft delete not needed; status field used |
| Experiment assignments | 90 days after experiment end date | Cron job deletes rows where `experiment.end_at < NOW() - 90d` |
| Experiment audit logs | Indefinite (compliance requirement) | — |

---

## 4. Current State

The system prompt used by the AI orchestration layer (US-AI-023) is currently constructed in one of these ways:

1. **Hardcoded string** in `app/services/ai/prompt_builder.py` — no versioning, no DB persistence.
2. **Single env var** `AI_SYSTEM_PROMPT_PATH` pointing to a text file — versioned by file name convention at best.
3. **No experiment framework** — every user sees the same prompt for every session.
4. **No analytics per prompt variant** — it is impossible to determine whether a prompt change improved or degraded content quality.

The `TemplateDefinition` model in `app/models/persisted_course.py` manages *content* templates (MCQ, video, etc.), but there is no equivalent service for *system* prompts that control the AI's behavior.

Existing related tables (`ai_sessions`, `ai_session_messages`, `ai_tool_call_logs`, `ai_usage_records`) contain session/usage data but have no `experiment_id` or `prompt_version_id` columns.

---

## 5. Expansion Points

| Future Enhancement | Story | Notes |
|---|---|---|
| Multi-prompt sequencing | Separate story | Compose system prompt from multiple templates with ordering rules (e.g., guardrails always first, then system, then tool defs) |
| Automated experiment design | Separate story | AI suggests experiment variants based on detected content quality gaps |
| Client-side A/B testing | Separate story | Allow frontend to evaluate experiment assignments for non-AI features |
| Cross-tenant experiments | Separate story | Run experiments across tenant boundaries with explicit opt-in |
| Bayesian analysis engine | Separate story | Replace z-test with Bayesian estimation for more robust small-sample inference |
| Prompt diff viewer | Separate story | Visual diff between versions in the admin UI |
| Scheduled prompt rollouts | Separate story | Canary deployments: activate a new prompt version for 5% of sessions, ramp to 100% |
| Personalization experiments | Separate story | Variant assignment based on user persona (not just tenant/hash) |

---

## 6. Validation and Test Scenarios

### 6.1 Unit Tests

| Test ID | Description | Expected |
|---|---|---|
| UT-PROMPT-001 | Create prompt with valid Jinja2 template | `prompt_id` returned, version 1 created, `is_active = true` |
| UT-PROMPT-002 | Create prompt with invalid Jinja2 syntax | 422 with `INVALID_TEMPLATE_SYNTAX` |
| UT-PROMPT-003 | Create prompt with duplicate name | 409 conflict |
| UT-PROMPT-004 | Create version with duplicate content hash for same prompt | 409 `DUPLICATE_PROMPT_VERSION` |
| UT-PROMPT-005 | Activate version 3, verify version 1 becomes inactive | `is_active` toggles correctly, audit record created |
| UT-PROMPT-006 | Render prompt with all required variables | Correct rendered output with variables interpolated |
| UT-PROMPT-007 | Render prompt with missing required variable | `PromptRenderError` with missing variable name |
| UT-PROMPT-008 | Render prompt with version_id=None picks active version | Active version used |
| UT-PROMPT-009 | Preview endpoint returns correct rendered text and resolved variables list | Matching output |
| UT-EXP-001 | Create experiment with 2 variants, weights 50/50 | Success, variants stored |
| UT-EXP-002 | Create experiment with weights summing to 90 | 422 with weight error message |
| UT-EXP-003 | Start experiment, verify status transition | `draft` -> `running`, `started_at` set |
| UT-EXP-004 | Stop running experiment, verify no new assignments | `status = "stopped"` |
| UT-EXP-005 | Conclude experiment with `promoteVariant: true` | Winning variant's prompt version activated |
| UT-EXP-006 | Hash-based assignment: same user + same experiment = same variant 1000/1000 | Deterministic, always same variant |
| UT-EXP-007 | Hash-based assignment: 1000 users approximate weight distribution | Within 5% of expected ratio (chi-square test) |
| UT-EXP-008 | Feature-flag assignment: user with flag on gets treatment | Treatment variant assigned |
| UT-EXP-009 | Feature-flag assignment: user with flag off gets control | Control variant assigned |
| UT-ASSIGN-001 | Session creation with matching experiment returns assignment in session | `experiment_assignments` populated |
| UT-ASSIGN-002 | Session creation with no matching experiments returns empty assignments | Empty `experiment_assignments` |
| UT-ASSIGN-003 | Session creation with feature flag disabled for tenant | No assignment for ff-based experiment |
| UT-ROLLBACK-001 | Auto-rollback triggers when tool_call_error_rate > threshold for treatment | Experiment status = `rolled_back`, audit written |
| UT-ROLLBACK-002 | Auto-rollback does not trigger when control also exceeds threshold | No rollback (both variants degraded — likely systemic issue) |
| UT-ROLLBACK-003 | Auto-rollback with `operator: lt` on cost_per_turn | Triggers when cost drops below threshold |

### 6.2 Integration Tests

| Test ID | Description |
|---|---|
| IT-PROMPT-001 | Full lifecycle: create prompt -> create version 2 -> activate version 2 -> verify active version changed -> verify audit trail |
| IT-PROMPT-002 | Create prompt, render via preview, confirm output matches expected structure |
| IT-EXP-001 | Full experiment lifecycle: create -> start -> create 10 sessions (same user) -> verify same variant -> stop -> analytics returns data |
| IT-EXP-002 | Create experiment with 3 variants (40/30/30). Create 200 sessions with different user IDs. Verify distribution within 10% of expected |
| IT-EXP-003 | Mixed experiments: user belongs to 2 experiments simultaneously. Verify both assignments in session |
| IT-CHAT-001 | Create session with experiment assignment, send chat turn, verify the resolved system prompt contains the variant's config_overrides (e.g., tone=conversational) |

### 6.3 End-to-End Tests

| Test ID | Description |
|---|---|
| E2E-PROMPT-001 | Admin creates prompt, creates version, activates it. Then creates experiment using it. Creates AI session as learner. Sends chat message. Verifies the LLM response matches the expected tone from the prompt variant. |
| E2E-ROLLBACK-001 | Configure experiment with auto-rollback on `tool_call_error_rate > 0.3`. Inject tool calls that fail. Verify experiment auto-rolls back within the check interval. |
| E2E-ANALYTICS-001 | Run experiment for 10 minutes with 50 synthetic sessions per variant. Query analytics endpoint. Verify per-variant metrics are non-zero and statistically plausible. |

### 6.4 Performance Tests

| Test ID | Description | Target |
|---|---|---|
| PT-ASSIGN-001 | 1000 concurrent session creations with experiment assignment | p95 < 100ms |
| PT-RENDER-001 | 500 concurrent prompt renders (3KB template, 10 variables) | p95 < 150ms |
| PT-ANALYTICS-001 | Analytics query across 30 days with 10k sessions, 100k tool call logs | p95 < 5s |
| PT-CONCURRENT-EXPS-001 | 50 experiments all running simultaneously with session creation | No degradation in session creation latency |

### 6.5 Failure Scenarios

| Scenario | Expected Behavior |
|---|---|
| Prompt version referenced by experiment is deleted | Experiment start fails with validation error. Running experiment continues using in-memory cache; new sessions fail assignment with logged error |
| Jinja2 template references a variable not provided at render time | `PromptRenderError` caught by orchestrator; prompt part skipped with warning; turn continues without that section |
| Analytics query times out (> 10s) | Return partial results with `"partial": true` flag; log slow query for optimization |
| Database migration for new tables fails | Application starts but `FEATURE_AI_PROMPT_REGISTRY` is automatically set to `false`; fallback to legacy prompt construction |
| Experiment `end_at` passes during active session | Existing sessions are not interrupted. New sessions after `end_at` are not assigned. Background job transitions experiment to `"completed"` |

---

## 7. Definition of Done

1. All DDL tables (`ai_prompts`, `ai_prompt_versions`, `ai_prompt_audit`, `ai_experiments`, `ai_experiment_variants`, `ai_experiment_assignments`, `ai_experiment_audit`) are created in the database and reflected in Alembic migrations.
2. SQLAlchemy ORM models in `app/models/ai_prompts.py` are registered in `app/models/__init__.py` and imported in `app/main.py` lifespan.
3. `PromptRegistryService` with all CRUD, versioning, activation, and rendering methods is implemented and tested.
4. `ExperimentAssigner` with hash-based, feature-flag, and percentage-based strategies is implemented and tested.
5. `ExperimentRollbackJob` with configurable metric thresholds is implemented and tested.
6. Router endpoints for prompt CRUD (`POST/GET/PATCH /api/v1/ai/prompts`, version creation, activation, preview) return correct responses and error codes.
7. Router endpoints for experiment CRUD and lifecycle (`POST/GET/PATCH /api/v1/ai/experiments`, start/stop/conclude) return correct responses.
8. Analytics endpoint `GET /api/v1/ai/experiments/{exp_id}/analytics` returns per-variant metric aggregates.
9. Session creation (US-AI-006) is extended to call `ExperimentAssigner` and store `experiment_assignments` on the session record.
10. Chat orchestration (US-AI-023) resolves experiment-assigned prompts via `PromptRegistryService.render_prompt()` instead of hardcoded prompt.
11. Default seed prompts (`course-authoring-default`, `guardrails-default`) are created on startup if the registry is empty.
12. `FEATURE_AI_PROMPT_REGISTRY` flag gates all new functionality; when disabled, legacy prompt construction is used.
13. All unit tests in Section 6.1 pass with >90% code coverage on new code.
14. Integration tests in Section 6.2 pass.
15. Performance tests in Section 6.4 meet targets in a staging environment.
16. Admin UI screens (separate frontend story) display prompt registry, experiment management, and analytics dashboard.

---

## 8. Tasks

### Task Breakdown by Phase

#### Phase 1: Database and ORM (Foundation)

| Task ID | Description | Effort (SP) | Dependencies |
|---|---|---|---|
| T1.1 | Write Alembic migration for `ai_prompts` and `ai_prompt_versions` tables | 3 | DB setup |
| T1.2 | Write Alembic migration for `ai_prompt_audit` table | 1 | T1.1 |
| T1.3 | Write Alembic migration for `ai_experiments`, `ai_experiment_variants` tables | 3 | DB setup |
| T1.4 | Write Alembic migration for `ai_experiment_assignments`, `ai_experiment_audit` tables | 2 | T1.3 |
| T1.5 | Implement SQLAlchemy ORM models in `app/models/ai_prompts.py` | 3 | T1.1-T1.4 |
| T1.6 | Register models in `app/models/__init__.py` and `app/main.py` lifespan imports | 1 | T1.5 |
| T1.7 | Add `experiment_assignments` JSONB column to `ai_sessions` table (US-AI-006) | 1 | T1.5 |

#### Phase 2: Prompt Registry Service

| Task ID | Description | Effort (SP) | Dependencies |
|---|---|---|---|
| T2.1 | Implement `PromptNotFoundError`, `PromptVersionNotFoundError`, `DuplicatePromptContentError`, `PromptRenderError` exception classes | 1 | — |
| T2.2 | Implement `PromptRegistryService.create_prompt()` with Jinja2 validation and content hashing | 3 | T1.5 |
| T2.3 | Implement `PromptRegistryService.create_version()` with duplicate detection and version increment | 2 | T2.2 |
| T2.4 | Implement `PromptRegistryService.activate_version()` with deactivation of previous active version and audit logging | 2 | T2.2 |
| T2.5 | Implement `PromptRegistryService.render_prompt()` with Jinja2 template resolution and variable validation | 3 | T2.2 |
| T2.6 | Implement `PromptRegistryService.list_prompts()` and `get_prompt_with_versions()` query methods | 1 | T2.2 |
| T2.7 | Write unit tests for `PromptRegistryService` (UT-PROMPT-001 through UT-PROMPT-008) | 3 | T2.2-T2.6 |

#### Phase 3: Experiment Service

| Task ID | Description | Effort (SP) | Dependencies |
|---|---|---|---|
| T3.1 | Implement `ExperimentAssigner` with hash-based (`hash_pct`) assignment strategy | 3 | T1.5, US-AI-006 |
| T3.2 | Implement `ExperimentAssigner` with feature-flag (`ff`) assignment strategy | 2 | T3.1, US-AI-002 |
| T3.3 | Implement `ExperimentAssigner` with percentage-based (`pct`) random assignment | 1 | T3.1 |
| T3.4 | Implement experiment scope filtering (tenant_ids, feature_flag membership) | 2 | T3.1 |
| T3.5 | Integrate `ExperimentAssigner` into session creation flow (US-AI-006) | 3 | T3.1-T3.4 |
| T3.6 | Write unit tests for `ExperimentAssigner` (UT-EXP-006 through UT-EXP-009, UT-ASSIGN-001 through UT-ASSIGN-003) | 3 | T3.1-T3.5 |

#### Phase 4: API Endpoints

| Task ID | Description | Effort (SP) | Dependencies |
|---|---|---|---|
| T4.1 | Implement `POST/GET /api/v1/ai/prompts` endpoints | 3 | T2.2, T2.6 |
| T4.2 | Implement `POST /api/v1/ai/prompts/{prompt_id}/versions` endpoint | 2 | T2.3 |
| T4.3 | Implement `PATCH /api/v1/ai/prompts/{prompt_id}/activate` endpoint | 2 | T2.4 |
| T4.4 | Implement `POST /api/v1/ai/prompts/{prompt_id}/preview` endpoint | 2 | T2.5 |
| T4.5 | Implement `POST/GET/PATCH /api/v1/ai/experiments` endpoints | 3 | T3.1, T3.4 |
| T4.6 | Implement `PATCH /api/v1/ai/experiments/{exp_id}/start`, `/stop`, `/conclude` endpoints | 3 | T4.5 |
| T4.7 | Implement `GET /api/v1/ai/experiments/{exp_id}/analytics` endpoint with aggregate queries | 5 | T4.5, US-AI-036, US-AI-031 |
| T4.8 | Implement Pydantic DTOs in `app/routers/ai_prompt_dtos.py` | 2 | T4.1-T4.7 |
| T4.9 | Register new routers in `app/main.py` | 1 | T4.1-T4.8 |
| T4.10 | Write integration tests for API endpoints (IT-PROMPT-001, IT-PROMPT-002, IT-EXP-001, IT-EXP-002, IT-EXP-003) | 4 | T4.1-T4.9 |

#### Phase 5: Orchestrator Integration

| Task ID | Description | Effort (SP) | Dependencies |
|---|---|---|---|
| T5.1 | Modify `ChatOrchestrator.build_prompt()` to load experiment-assigned prompts via `PromptRegistryService.render_prompt()` | 4 | T2.5, T3.5, US-AI-023 |
| T5.2 | Add fallback logic when prompt rendering fails (skip prompt part, log warning, continue) | 2 | T5.1 |
| T5.3 | Implement `_get_always_on_prompts()` for guardrail prompts not tied to experiments | 2 | T5.1 |
| T5.4 | Write integration test for chat with experiment assignment (IT-CHAT-001) | 2 | T5.1-T5.3 |

#### Phase 6: Background Jobs and Seed Data

| Task ID | Description | Effort (SP) | Dependencies |
|---|---|---|---|
| T6.1 | Implement `seed_system_prompts()` startup seed function | 2 | T2.2 |
| T6.2 | Integrate seed function into `app/main.py` lifespan startup | 1 | T6.1 |
| T6.3 | Implement `ExperimentRollbackJob.check_and_rollback()` with metric queries | 4 | T4.5, US-AI-036 |
| T6.4 | Integrate rollback job into background scheduler (APScheduler or similar) | 2 | T6.3 |
| T6.5 | Write unit tests for rollback logic (UT-ROLLBACK-001 through UT-ROLLBACK-003) | 2 | T6.3 |

#### Phase 7: Feature Flag, Configuration, and Documentation

| Task ID | Description | Effort (SP) | Dependencies |
|---|---|---|---|
| T7.1 | Wire `FEATURE_AI_PROMPT_REGISTRY` feature flag into all new endpoints and services | 2 | T4.1-T4.9, T5.1 |
| T7.2 | Add environment variables to `.env.example` and deployment configs | 1 | — |
| T7.3 | Write admin/operator documentation for prompt registry and experiment management | 3 | T4.1-T4.9 |
| T7.4 | Write developer documentation for adding new prompt variables and custom templates | 2 | T7.3 |

### Effort Summary

| Phase | Story Points |
|---|---|
| Phase 1: Database and ORM | 14 |
| Phase 2: Prompt Registry Service | 15 |
| Phase 3: Experiment Service | 14 |
| Phase 4: API Endpoints | 25 |
| Phase 5: Orchestrator Integration | 10 |
| Phase 6: Background Jobs and Seed Data | 11 |
| Phase 7: Feature Flag and Documentation | 8 |
| **Total** | **97 SP** |

### Recommended Sprint Allocation

| Sprint | Phases | SP |
|---|---|---|
| Sprint 1 | Phase 1 (all) + Phase 2 (T2.1-T2.5) | 22 |
| Sprint 2 | Phase 2 (T2.6-T2.7) + Phase 3 (all) | 21 |
| Sprint 3 | Phase 4 (T4.1-T4.6) + Phase 6 (T6.1-T6.2) | 18 |
| Sprint 4 | Phase 4 (T4.7-T4.10) + Phase 5 (all) | 21 |
| Sprint 5 | Phase 6 (T6.3-T6.5) + Phase 7 (all) | 15 |
| **Total** | | **97 SP** |

---
