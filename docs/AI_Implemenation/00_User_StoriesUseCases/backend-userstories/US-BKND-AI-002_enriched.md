# US-BKND-AI-002 — Configure AI Feature Flags, Models, and Provider Routing

**Priority:** MUST
**Story Points:** 5
**Sprint:** 1 (Foundations)
**Depends On:** US-AI-PR01 through US-AI-PR05 (mock auth/authz/tenant/session/user)
**Unlocks:** US-BKND-AI-003 (API module), US-BKND-AI-026 (multi-provider routing), US-BKND-AI-036 (cost tracking)

---

## 1. Functional Specification

### 1.1 User Story

As an **Admin/Operator**, I want configurable AI feature flags and model/provider settings via environment variables with startup validation, so that AI capabilities can be rolled out safely, gated by environment, and adjusted without code changes.

### 1.2 Functional Requirements

**FR-1: Master AI Feature Flag**
`AI_AUTHORING_ENABLED` env var (boolean, default `false`). When `false`, all AI routes return 404, no AI UI renders. When `true`, AI routes are mounted and operational.

**FR-2: Model Allowlist**
The system MUST maintain an allowlist of permitted AI model IDs. Requests specifying an unsupported model MUST be rejected with a clear error including the supported model list.

**FR-3: Primary/Fallback Model Configuration**
`AI_PRIMARY_MODEL` and `AI_FALLBACK_MODEL` env vars specifying the default model chain. Both MUST be validated against the allowlist at startup.

**FR-4: Token Budget Configuration**
`AI_MAX_INPUT_TOKENS`, `AI_MAX_OUTPUT_TOKENS`, `AI_TOTAL_TOKEN_BUDGET_PER_REQUEST` env vars with sensible defaults. Budgets MUST be enforced per-request.

**FR-5: Retry and Timeout Configuration**
`AI_MAX_RETRIES` (default 1), `AI_REQUEST_TIMEOUT_SECONDS` (default 30), `AI_RATE_LIMIT_CALLS_PER_HOUR` (default 100), `AI_RATE_LIMIT_CALLS_PER_DAY` (default 500).

**FR-6: Cost Cap Configuration**
`AI_MONTHLY_COST_CAP_USD` (default 500.0). Optional per-tenant override via organization settings (US-AI-PR05).

**FR-7: Startup Validation**
All config values MUST be validated at application startup. Invalid values MUST cause a clear CRITICAL log message. Missing `ANTHROPIC_API_KEY` when `AI_AUTHORING_ENABLED=true` MUST log CRITICAL and set AI status to `degraded`.

**FR-8: Environment-Specific Profiles**
Dev: loose limits, mock mode allowed. Staging: production-like limits, real API keys optional. Production: strict limits, mock mode FORBIDDEN. `ENVIRONMENT` env var drives profile selection.

**FR-9: Feature Flag Status Endpoint**
`GET /api/v1/ai/feature-status` returns `{aiAuthoringEnabled: bool, aiStatus: "configured"|"degraded"|"unavailable", activeModel: string, fallbackModel: string, rateLimits: {...}}`.

**FR-10: Hot Reload Support**
Configuration changes via environment variables MUST take effect on next request (no server restart) for non-critical settings. Model changes MAY require restart.

### 1.3 User Flow

**Happy Path:**
1. Operator sets `AI_AUTHORING_ENABLED=true`, `ANTHROPIC_API_KEY=sk-ant-...`, `AI_PRIMARY_MODEL=claude-sonnet-4-20250514` in `.env`
2. Server starts → validates all config → logs `AI authoring ENABLED. Primary: claude-sonnet-4-20250514. Rate limits: 100/h`
3. Frontend calls `GET /api/v1/ai/feature-status` → `{aiAuthoringEnabled: true, aiStatus: "configured", ...}`
4. AI button renders. User can start AI sessions.

**Error Path — Missing API Key:**
1. `AI_AUTHORING_ENABLED=true` but `ANTHROPIC_API_KEY` not set
2. Startup logs: `CRITICAL: AI enabled but ANTHROPIC_API_KEY missing. AI status: degraded`
3. Feature status returns `aiStatus: "degraded"`
4. AI routes return 503 with `{"code": "AI_NOT_CONFIGURED"}`

**Error Path — Invalid Model:**
1. `AI_PRIMARY_MODEL=gpt-5-super` (not in allowlist)
2. Startup fails validation → CRITICAL log → AI status: degraded until fixed

---

## 2. Technical Specification

### 2.1 Configuration Module

**File:** `app/services/ai/config.py`

```python
"""
AI Configuration Service

Loads and validates all AI-related configuration from environment variables.
Provides a singleton AIConfig instance for use across all AI services.

TODO(AUTH): When real auth is implemented, add per-tenant config overrides
from the tenant registry service (US-AI-PR05 provides mock org settings).
"""

import os
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum

logger = logging.getLogger("ai_authoring")

class AIStatus(str, Enum):
    CONFIGURED = "configured"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"

class ModelTier(str, Enum):
    PLANNER = "planner"       # Fast/cheap model for structure decisions
    GENERATOR = "generator"   # Premium model for content generation
    REPAIR = "repair"         # Fast model for JSON repair
    SAFETY = "safety"         # Deterministic model for safety checks

@dataclass
class ModelConfig:
    """Configuration for a specific AI model."""
    id: str                          # Internal model identifier
    provider: str                    # "anthropic" | "openai" | etc.
    api_model_name: str              # Model name as known by provider API
    tier: ModelTier                  # Planner, generator, repair, or safety
    max_tokens: int = 4096
    cost_per_1k_input_tokens: float = 0.0
    cost_per_1k_output_tokens: float = 0.0
    supports_tool_calling: bool = True
    supports_structured_output: bool = True
    status: str = "active"           # active | hidden | deprecated

@dataclass
class AIConfig:
    """Global AI configuration singleton."""
    ai_authoring_enabled: bool = False
    ai_status: AIStatus = AIStatus.UNAVAILABLE
    environment: str = "development"
    
    # API key
    anthropic_api_key: Optional[str] = None
    
    # Model routing
    primary_model_id: str = "claude-sonnet-4-20250514"
    fallback_model_id: str = "claude-haiku-4-20250514"
    
    # Limits
    max_input_tokens: int = 8000
    max_output_tokens: int = 4096
    total_token_budget_per_request: int = 12000
    max_retries: int = 1
    request_timeout_seconds: int = 30
    rate_limit_calls_per_hour: int = 100
    rate_limit_calls_per_day: int = 500
    monthly_cost_cap_usd: float = 500.0
    
    # Safety
    prompt_safety_enabled: bool = True
    output_safety_enabled: bool = True
    mock_mode_allowed: bool = True

    # Model registry
    _model_registry: Dict[str, ModelConfig] = field(default_factory=dict)

    def __post_init__(self):
        self._model_registry = self._build_model_registry()
        self._validate()

    def _build_model_registry(self) -> Dict[str, ModelConfig]:
        """Build the allowlist of supported models.

        TODO(MODEL): When adding new providers, extend this registry.
        Production will load from a config file or database.
        """
        return {
            "claude-sonnet-4-20250514": ModelConfig(
                id="claude-sonnet-4-20250514",
                provider="anthropic",
                api_model_name="claude-sonnet-4-20250514",
                tier=ModelTier.GENERATOR,
                max_tokens=4096,
                cost_per_1k_input_tokens=0.003,
                cost_per_1k_output_tokens=0.015,
            ),
            "claude-haiku-4-20250514": ModelConfig(
                id="claude-haiku-4-20250514",
                provider="anthropic",
                api_model_name="claude-haiku-4-20250514",
                tier=ModelTier.PLANNER,
                max_tokens=2048,
                cost_per_1k_input_tokens=0.0008,
                cost_per_1k_output_tokens=0.004,
            ),
        }

    def _validate(self) -> None:
        """Validate configuration at startup. Log issues; don't crash."""
        if not self.ai_authoring_enabled:
            self.ai_status = AIStatus.UNAVAILABLE
            logger.info("AI authoring DISABLED (AI_AUTHORING_ENABLED=false)")
            return

        errors = []
        if not self.anthropic_api_key:
            errors.append("ANTHROPIC_API_KEY is not set")
        
        if self.primary_model_id not in self._model_registry:
            errors.append(f"Primary model '{self.primary_model_id}' not in allowlist")
        if self.fallback_model_id not in self._model_registry:
            errors.append(f"Fallback model '{self.fallback_model_id}' not in allowlist")
        
        if self.environment == "production" and self.mock_mode_allowed:
            errors.append("Mock mode MUST NOT be allowed in production")
        
        if errors:
            self.ai_status = AIStatus.DEGRADED
            for err in errors:
                logger.critical("AI config error: %s", err)
        else:
            self.ai_status = AIStatus.CONFIGURED
            logger.info(
                "AI configured. Primary: %s, Fallback: %s, Rate limit: %d/h",
                self.primary_model_id, self.fallback_model_id, self.rate_limit_calls_per_hour,
            )

    def get_model(self, model_id: str) -> ModelConfig:
        """Get a model config by ID. Raises ValueError if unsupported."""
        model = self._model_registry.get(model_id)
        if not model:
            supported = list(self._model_registry.keys())
            raise ValueError(f"Unknown model '{model_id}'. Supported: {supported}")
        if model.status == "deprecated":
            logger.warning("Model '%s' is deprecated; prefer '%s'", model_id, self.primary_model_id)
        return model

    def get_primary_model(self) -> ModelConfig:
        return self.get_model(self.primary_model_id)

    def get_fallback_model(self) -> ModelConfig:
        return self.get_model(self.fallback_model_id)

    def get_model_for_tier(self, tier: ModelTier) -> ModelConfig:
        """Get the best available model for a given tier."""
        for model in self._model_registry.values():
            if model.tier == tier and model.status == "active":
                return model
        return self.get_primary_model()  # fallback to primary


def load_ai_config() -> AIConfig:
    """Load AI configuration from environment variables.

    Called once at application startup.
    """
    return AIConfig(
        ai_authoring_enabled=os.getenv("AI_AUTHORING_ENABLED", "false").lower() in ("true", "1", "yes"),
        environment=os.getenv("ENVIRONMENT", "development"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        primary_model_id=os.getenv("AI_PRIMARY_MODEL", "claude-sonnet-4-20250514"),
        fallback_model_id=os.getenv("AI_FALLBACK_MODEL", "claude-haiku-4-20250514"),
        max_input_tokens=int(os.getenv("AI_MAX_INPUT_TOKENS", "8000")),
        max_output_tokens=int(os.getenv("AI_MAX_OUTPUT_TOKENS", "4096")),
        total_token_budget_per_request=int(os.getenv("AI_TOTAL_TOKEN_BUDGET", "12000")),
        max_retries=int(os.getenv("AI_MAX_RETRIES", "1")),
        request_timeout_seconds=int(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "30")),
        rate_limit_calls_per_hour=int(os.getenv("AI_RATE_LIMIT_CALLS_PER_HOUR", "100")),
        rate_limit_calls_per_day=int(os.getenv("AI_RATE_LIMIT_CALLS_PER_DAY", "500")),
        monthly_cost_cap_usd=float(os.getenv("AI_MONTHLY_COST_CAP_USD", "500.0")),
        prompt_safety_enabled=os.getenv("AI_PROMPT_SAFETY_ENABLED", "true").lower() in ("true", "1", "yes"),
        output_safety_enabled=os.getenv("AI_OUTPUT_SAFETY_ENABLED", "true").lower() in ("true", "1", "yes"),
        mock_mode_allowed=os.getenv("AUTH_MOCK_MODE", "enabled").lower() in ("enabled", "1", "true", "yes"),
    )


# Global singleton — initialized once at startup
ai_config: Optional[AIConfig] = None

def get_ai_config() -> AIConfig:
    """Get the global AI configuration singleton."""
    global ai_config
    if ai_config is None:
        ai_config = load_ai_config()
    return ai_config
```

### 2.2 Feature Status Endpoint

**File:** `app/routers/ai_config.py`

```python
from fastapi import APIRouter
from app.services.ai.config import get_ai_config

router = APIRouter(prefix="/api/v1/ai", tags=["AI Configuration"])

@router.get("/feature-status")
async def get_ai_feature_status():
    """Return current AI feature status for frontend consumption."""
    config = get_ai_config()
    primary = config.get_primary_model()
    return {
        "aiAuthoringEnabled": config.ai_authoring_enabled,
        "aiStatus": config.ai_status.value,
        "activeModel": {
            "id": primary.id,
            "provider": primary.provider,
            "tier": primary.tier.value,
        },
        "fallbackModel": {
            "id": config.get_fallback_model().id,
            "provider": config.get_fallback_model().provider,
            "tier": config.get_fallback_model().tier.value,
        },
        "rateLimits": {
            "callsPerHour": config.rate_limit_calls_per_hour,
            "callsPerDay": config.rate_limit_calls_per_day,
        },
    }
```

### 2.3 Environment Variables

```bash
# .env.example additions

# ── AI Feature Flags ───────────────────────────────────────────
AI_AUTHORING_ENABLED=false                 # Master AI on/off switch
ENVIRONMENT=development                    # development | staging | production

# ── AI Model Configuration ─────────────────────────────────────
ANTHROPIC_API_KEY=                         # Required when AI enabled
AI_PRIMARY_MODEL=claude-sonnet-4-20250514
AI_FALLBACK_MODEL=claude-haiku-4-20250514

# ── AI Limits ──────────────────────────────────────────────────
AI_MAX_INPUT_TOKENS=8000
AI_MAX_OUTPUT_TOKENS=4096
AI_TOTAL_TOKEN_BUDGET=12000
AI_MAX_RETRIES=1
AI_REQUEST_TIMEOUT_SECONDS=30
AI_RATE_LIMIT_CALLS_PER_HOUR=100
AI_RATE_LIMIT_CALLS_PER_DAY=500
AI_MONTHLY_COST_CAP_USD=500.0

# ── AI Safety ──────────────────────────────────────────────────
AI_PROMPT_SAFETY_ENABLED=true
AI_OUTPUT_SAFETY_ENABLED=true
```

---

## 3. Non-Functional Requirements

### 3.1 Performance
- `get_ai_config()` MUST return in < 0.1ms (cached singleton)
- Feature status endpoint MUST respond in < 5ms
- Startup config validation MUST complete in < 100ms

### 3.2 Security
- `ANTHROPIC_API_KEY` MUST NOT be logged or exposed in any endpoint
- `AUTH_MOCK_MODE=enabled` MUST be rejected at startup in production
- Feature status endpoint MUST NOT expose API key or internal configuration

### 3.3 Reliability
- Invalid config MUST NOT crash the application (graceful degradation)
- Config singleton MUST be thread-safe (read-only after initialization)

---

## 4. Current State Assessment

### 4.1 What Exists
- `app/utils/feature_flags.py` — existing feature flag system with `ai_suggestions` flag
- `app/db/config.py` — database configuration loading from env

### 4.2 What Must Be Built (Net-New)
- `app/services/ai/config.py` — AI configuration service (as specified above)
- `app/routers/ai_config.py` — Feature status endpoint
- `.env.example` — Add all AI config variables

### 4.3 What Must Be Modified
- `app/main.py` — Import `load_ai_config()` and call at startup; conditionally mount `ai_config.router` and other AI routers

---

## 5. Expansion Points

### 5.1 Technical Expansion
1. **Database-backed config**: Store model registry and tenant overrides in DB instead of env vars
2. **Dynamic model registry**: Load model config from a JSON/YAML file for easier updates
3. **Config hot-reload**: Watch for env var changes and update singleton without restart

### 5.2 Functional Expansion
1. **Per-tenant config overrides**: Different rate limits and model selections per organization
2. **Cost-based routing**: Route to cheapest model that meets quality requirements
3. **Usage-based degradation**: Auto-switch to fallback model when approaching budget cap

---

## 6. Validation & Testing

### 6.1 Unit Tests
- TC-002-01: `AI_AUTHORING_ENABLED=false` → ai_status=UNAVAILABLE, no API key errors logged
- TC-002-02: `AI_AUTHORING_ENABLED=true` + valid API key → ai_status=CONFIGURED
- TC-002-03: `AI_AUTHORING_ENABLED=true` + missing API key → ai_status=DEGRADED, CRITICAL log
- TC-002-04: Invalid `AI_PRIMARY_MODEL` → ai_status=DEGRADED, error logged
- TC-002-05: `get_model("unsupported-model")` → ValueError with supported model list
- TC-002-06: `ENVIRONMENT=production` + `AUTH_MOCK_MODE=enabled` → ai_status=DEGRADED
- TC-002-07: `get_model_for_tier(ModelTier.PLANNER)` returns cheapest active model

### 6.2 Integration Tests
- TC-002-I1: `GET /api/v1/ai/feature-status` returns correct status when disabled
- TC-002-I2: `GET /api/v1/ai/feature-status` returns correct model info when enabled
- TC-002-I3: AI routes return 404 when feature flag is off

### 6.3 E2E Tests
- TC-002-E1: Frontend hides AI button when feature-status returns disabled
- TC-002-E2: Frontend shows AI button when feature-status returns configured

---

## 7. Definition of Done

- [ ] `app/services/ai/config.py` implemented with `AIConfig`, `ModelConfig`, `ModelTier`, `AIStatus`
- [ ] `load_ai_config()` reads all env vars with defaults
- [ ] Startup validation passes without API key when AI is disabled
- [ ] Startup validation degrades gracefully when API key missing
- [ ] `get_ai_config()` returns thread-safe singleton
- [ ] `GET /api/v1/ai/feature-status` endpoint working
- [ ] `.env.example` updated with all AI config variables
- [ ] AI routers conditionally mounted based on feature flag
- [ ] `AI_AUTHORING_ENABLED=false` → AI routes return 404
- [ ] All unit tests pass (7 scenarios)
- [ ] All integration tests pass (3 scenarios)
- [ ] Manual QA: toggle flag, verify UI hides/shows AI button
- [ ] Code reviewed with sign-off on env var naming convention
- [ ] CRITICAL log messages verified for degraded scenarios
- [ ] No API key leaked in logs or endpoints

---

## 8. Tasks & Sub-Tasks

| Task ID | Description | Owner | Est. | Depends On |
|---|---|---|---|---|
| T1 | Create `app/services/ai/__init__.py` package | Backend | 0.25h | — |
| T2 | Create `app/services/ai/config.py` with `AIConfig`, `ModelConfig`, `ModelTier`, `AIStatus`, `load_ai_config()`, `get_ai_config()` | Backend | 3h | T1 |
| T3 | Create `app/routers/ai_config.py` with `/feature-status` endpoint | Backend | 1h | T2 |
| T4 | Modify `app/main.py` to call `load_ai_config()` at startup and conditionally mount AI routers | Backend | 1.5h | T2, T3 |
| T5 | Update `.env.example` with AI configuration section | Backend | 0.5h | T2 |
| T6 | Write 7 unit tests for config loading and validation | Backend | 2h | T2 |
| T7 | Write 3 integration tests for feature-status endpoint and route gating | Backend | 1.5h | T3, T4 |
| T8 | Verify zero regression: all existing tests pass with AI_AUTHORING_ENABLED=false | Backend | 0.5h | T4 |
| T9 | Code review and sign-off | Lead | 1h | T6, T7 |
