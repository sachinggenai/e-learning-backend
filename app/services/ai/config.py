"""
AI Configuration Service.

Loads and validates all AI-related configuration from environment variables.
Provides a singleton AIConfig instance for use across all AI services.

TODO(AUTH): When real auth is implemented, add per-tenant config overrides
from the tenant registry service.

See: docs/AI_Implemenation/00_User_StoriesUseCases/backend-userstories/US-BKND-AI-002_enriched.md
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

logger = logging.getLogger("ai_authoring")


class AIStatus(str, Enum):
    """AI subsystem operational status."""
    CONFIGURED = "configured"    # AI enabled, all config valid, API key present
    DEGRADED = "degraded"        # AI enabled but config issues (missing key, etc.)
    UNAVAILABLE = "unavailable"  # AI disabled or critical failure


class ModelTier(str, Enum):
    """Model capability tiers for task-based routing."""
    PLANNER = "planner"        # Fast/cheap model for structure decisions
    GENERATOR = "generator"    # Premium model for content generation
    REPAIR = "repair"          # Fast model for JSON repair
    SAFETY = "safety"          # Dedicated model for safety/content checks


@dataclass
class ModelConfig:
    """Configuration for a specific AI model in the allowlist."""
    id: str                              # Internal model identifier
    provider: str                        # "anthropic", "openai", etc.
    api_model_name: str                  # Model name as known by provider API
    tier: ModelTier                      # Planner, generator, repair, or safety
    max_tokens: int = 4096
    cost_per_1k_input_tokens: float = 0.0
    cost_per_1k_output_tokens: float = 0.0
    supports_tool_calling: bool = True
    supports_structured_output: bool = True
    status: str = "active"              # active | hidden | deprecated


@dataclass
class AIConfig:
    """Global AI configuration singleton.

    Initialized once at application startup via load_ai_config().
    Read-only after initialization (thread-safe).
    """
    ai_authoring_enabled: bool = False
    ai_status: AIStatus = AIStatus.UNAVAILABLE
    environment: str = "development"

    # API key
    anthropic_api_key: Optional[str] = None

    # Model routing
    primary_model_id: str = "deepseek-v4-pro[1m]"
    fallback_model_id: str = "deepseek-v4-flash"

    # Token budgets
    max_input_tokens: int = 8000
    max_output_tokens: int = 4096
    total_token_budget_per_request: int = 12000

    # Retry and timeout
    max_retries: int = 1
    request_timeout_seconds: int = 30

    # Rate limits
    rate_limit_calls_per_hour: int = 100
    rate_limit_calls_per_day: int = 500

    # Cost
    monthly_cost_cap_usd: float = 500.0

    # Safety
    prompt_safety_enabled: bool = True
    output_safety_enabled: bool = True
    mock_mode_allowed: bool = True

    # ── Persistence TTLs (US-BKND-AI-004) ──────────────────────
    session_ttl_hours: int = 24
    proposal_ttl_minutes: int = 60
    confirmation_ttl_minutes: int = 10
    idempotency_ttl_hours: int = 24
    outbox_poll_interval_seconds: int = 5
    outbox_retry_max: int = 3

    # ── Session limits (US-BKND-AI-006) ───────────────────────
    max_active_sessions_per_user: int = 500
    session_cleanup_interval_minutes: int = 15
    rate_limit_create_session_per_hour: int = 20

    # ── TRD-CGQ Phase 1: Course Generation Quality ──────────────
    generation_provider: str = ""            # "ollama" | "anthropic" | "mock" — explicit override
    template_selector_llm_enabled: bool = False
    template_selector_model: str = "qwen2.5:7b"
    semantic_splitter_enabled: bool = False
    rules_based_mcq_min_questions: int = 3
    component_hierarchy_enabled: bool = False
    model_escalation_chain: list = field(default_factory=lambda: ["qwen2.5:7b", "phi3:mini", "mock"])

    # ── Similar Course Retrieval / RAG (US-BKND-AI-015) ────────
    enable_pgvector: bool = False
    embedding_provider_name: str = "mock"
    embedding_model: str = "text-embedding-ada-002"
    embedding_dimension: int = 1536
    similar_course_max_results: int = 20
    similar_course_cache_ttl_minutes: int = 60

    # ── Durable Workflow Engine (US-BKND-AI-034) ──────────
    workflow_enabled: bool = True
    workflow_worker_id: str = "worker-1"
    workflow_max_concurrency: int = 4
    workflow_poll_interval: float = 1.0
    workflow_heartbeat_interval: float = 5.0
    workflow_lock_timeout_ms: int = 5000
    workflow_stale_threshold: int = 30
    workflow_max_duration_seconds: int = 86400

    # Model registry (built at init)
    _model_registry: Dict[str, ModelConfig] = field(default_factory=dict)

    def __post_init__(self):
        self._model_registry = self._build_model_registry()
        self._validate()

    def _build_model_registry(self) -> Dict[str, ModelConfig]:
        """Build the allowlist of supported AI models.

        TODO(MODEL): Load from a config file or database table for
        easier updates. Add more models as they become available.
        """
        return {
            # ── Ollama local models (primary) ──────────────────────
            "qwen2.5:7b": ModelConfig(
                id="qwen2.5:7b",
                provider="ollama",
                api_model_name="qwen2.5:7b",
                tier=ModelTier.GENERATOR,
                max_tokens=8192,
                cost_per_1k_input_tokens=0.0,
                cost_per_1k_output_tokens=0.0,
                supports_tool_calling=True,
                supports_structured_output=True,
            ),
            "phi3:mini": ModelConfig(
                id="phi3:mini",
                provider="ollama",
                api_model_name="phi3:mini",
                tier=ModelTier.PLANNER,
                max_tokens=4096,
                cost_per_1k_input_tokens=0.0,
                cost_per_1k_output_tokens=0.0,
                supports_tool_calling=True,
                supports_structured_output=True,
            ),
            # ── Claude models (fallback) ──────────────────────────
            "claude-sonnet-4-20250514": ModelConfig(
                id="claude-sonnet-4-20250514",
                provider="anthropic",
                api_model_name="claude-sonnet-4-20250514",
                tier=ModelTier.GENERATOR,
                max_tokens=4096,
                cost_per_1k_input_tokens=0.003,
                cost_per_1k_output_tokens=0.015,
                supports_tool_calling=True,
                supports_structured_output=True,
            ),
            "claude-haiku-4-20250514": ModelConfig(
                id="claude-haiku-4-20250514",
                provider="anthropic",
                api_model_name="claude-haiku-4-20250514",
                tier=ModelTier.PLANNER,
                max_tokens=2048,
                cost_per_1k_input_tokens=0.0008,
                cost_per_1k_output_tokens=0.004,
                supports_tool_calling=True,
                supports_structured_output=True,
            ),
        }

    def _validate(self) -> None:
        """Validate configuration at startup.

        Logs issues; does NOT crash. AI features degrade gracefully
        when configuration is invalid.
        """
        if not self.ai_authoring_enabled:
            self.ai_status = AIStatus.UNAVAILABLE
            logger.info("AI authoring DISABLED (AI_AUTHORING_ENABLED=false)")
            return

        errors: List[str] = []

        if not self.anthropic_api_key:
            errors.append(
                "ANTHROPIC_API_KEY is not set — AI cannot make model calls"
            )

        if self.primary_model_id not in self._model_registry:
            errors.append(
                f"Primary model '{self.primary_model_id}' not in allowlist. "
                f"Supported: {list(self._model_registry.keys())}"
            )

        if self.fallback_model_id not in self._model_registry:
            errors.append(
                f"Fallback model '{self.fallback_model_id}' not in allowlist"
            )

        if self.environment == "production" and self.mock_mode_allowed:
            errors.append(
                "AUTH_MOCK_MODE must be DISABLED in production environment"
            )

        if self.primary_model_id == self.fallback_model_id:
            errors.append(
                "Primary and fallback models must be different"
            )

        if errors:
            self.ai_status = AIStatus.DEGRADED
            for err in errors:
                logger.critical("AI CONFIG ERROR: %s", err)
        else:
            self.ai_status = AIStatus.CONFIGURED
            logger.info(
                "AI authoring CONFIGURED. Primary: %s (%s), Fallback: %s (%s), "
                "Rate limit: %d calls/hour, Cost cap: $%.2f/month",
                self.primary_model_id,
                self.get_primary_model().tier.value,
                self.fallback_model_id,
                self.get_fallback_model().tier.value,
                self.rate_limit_calls_per_hour,
                self.monthly_cost_cap_usd,
            )

    def get_model(self, model_id: str) -> ModelConfig:
        """Get a model config by ID.

        Raises ValueError if the model is not in the allowlist.
        """
        model = self._model_registry.get(model_id)
        if model is None:
            supported = list(self._model_registry.keys())
            raise ValueError(
                f"Unknown model '{model_id}'. Supported models: {supported}"
            )
        if model.status == "deprecated":
            logger.warning(
                "Model '%s' is deprecated. Use '%s' instead.",
                model_id,
                self.primary_model_id,
            )
        return model

    def get_primary_model(self) -> ModelConfig:
        """Get the primary model configuration."""
        return self.get_model(self.primary_model_id)

    def get_fallback_model(self) -> ModelConfig:
        """Get the fallback model configuration."""
        return self.get_model(self.fallback_model_id)

    def get_model_for_tier(self, tier: ModelTier) -> ModelConfig:
        """Get the best available active model for a given tier."""
        for model in self._model_registry.values():
            if model.tier == tier and model.status == "active":
                return model
        # Fall back to primary model if no model matches the tier
        logger.warning(
            "No active model found for tier '%s', falling back to primary",
            tier.value,
        )
        return self.get_primary_model()

    def list_active_models(self) -> List[ModelConfig]:
        """Return all active (non-deprecated, non-hidden) models."""
        return [
            m for m in self._model_registry.values()
            if m.status == "active"
        ]


# ── Global singleton ──────────────────────────────────────────
_ai_config: Optional[AIConfig] = None


def load_ai_config() -> AIConfig:
    """Load AI configuration from environment variables.

    Called once at application startup. Safe to call multiple times
    (returns existing singleton after first call).
    """
    global _ai_config
    if _ai_config is not None:
        return _ai_config

    _ai_config = AIConfig(
        ai_authoring_enabled=_env_bool("AI_AUTHORING_ENABLED", False),
        environment=os.getenv("ENVIRONMENT", "development").lower(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"),
        primary_model_id=os.getenv(
            "AI_PRIMARY_MODEL", "deepseek-v4-pro[1m]"
        ),
        fallback_model_id=os.getenv(
            "AI_FALLBACK_MODEL", "deepseek-v4-flash"
        ),
        max_input_tokens=_env_int("AI_MAX_INPUT_TOKENS", 8000),
        max_output_tokens=_env_int("AI_MAX_OUTPUT_TOKENS", 4096),
        total_token_budget_per_request=_env_int("AI_TOTAL_TOKEN_BUDGET", 12000),
        max_retries=_env_int("AI_MAX_RETRIES", 1),
        request_timeout_seconds=_env_int("AI_REQUEST_TIMEOUT_SECONDS", 30),
        rate_limit_calls_per_hour=_env_int("AI_RATE_LIMIT_CALLS_PER_HOUR", 100),
        rate_limit_calls_per_day=_env_int("AI_RATE_LIMIT_CALLS_PER_DAY", 500),
        monthly_cost_cap_usd=_env_float("AI_MONTHLY_COST_CAP_USD", 500.0),
        prompt_safety_enabled=_env_bool("AI_PROMPT_SAFETY_ENABLED", True),
        output_safety_enabled=_env_bool("AI_OUTPUT_SAFETY_ENABLED", True),
        mock_mode_allowed=_env_bool("AUTH_MOCK_MODE", True),
        # ── Persistence TTLs (US-BKND-AI-004) ──────────────────
        session_ttl_hours=_env_int("AI_SESSION_TTL_HOURS", 24),
        proposal_ttl_minutes=_env_int("AI_PROPOSAL_TTL_MINUTES", 60),
        confirmation_ttl_minutes=_env_int("AI_CONFIRMATION_TTL_MINUTES", 10),
        idempotency_ttl_hours=_env_int("AI_IDEMPOTENCY_TTL_HOURS", 24),
        outbox_poll_interval_seconds=_env_int("AI_OUTBOX_POLL_INTERVAL_SECONDS", 5),
        outbox_retry_max=_env_int("AI_OUTBOX_RETRY_MAX", 3),
        # ── Session limits (US-BKND-AI-006) ────────────────────
        max_active_sessions_per_user=_env_int("AI_MAX_ACTIVE_SESSIONS", 5),
        session_cleanup_interval_minutes=_env_int("AI_SESSION_CLEANUP_INTERVAL_MINUTES", 15),
        rate_limit_create_session_per_hour=_env_int("AI_RATE_LIMIT_CREATE_SESSION_PER_HOUR", 20),
        # ── Similar Course Retrieval / RAG (US-BKND-AI-015) ────
        enable_pgvector=_env_bool("ENABLE_PGVECTOR", False),
        embedding_provider_name=os.getenv("EMBEDDING_PROVIDER", "mock").lower(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002"),
        embedding_dimension=_env_int("EMBEDDING_DIMENSION", 1536),
        similar_course_max_results=_env_int("SIMILAR_COURSE_MAX_RESULTS", 20),
        similar_course_cache_ttl_minutes=_env_int("SIMILAR_COURSE_CACHE_TTL_MINUTES", 60),
        # ── Durable Workflow Engine (US-BKND-AI-034) ──────
        workflow_enabled=_env_bool("WORKFLOW_ENABLED", True),
        workflow_worker_id=os.getenv("WORKFLOW_WORKER_ID", "worker-1"),
        workflow_max_concurrency=_env_int("WORKFLOW_MAX_CONCURRENCY", 4),
        workflow_poll_interval=float(os.getenv("WORKFLOW_POLL_INTERVAL", "1.0")),
        workflow_heartbeat_interval=float(os.getenv("WORKFLOW_HEARTBEAT_INTERVAL", "5.0")),
        workflow_lock_timeout_ms=_env_int("WORKFLOW_LOCK_TIMEOUT_MS", 5000),
        workflow_stale_threshold=_env_int("WORKFLOW_STALE_THRESHOLD", 30),
        workflow_max_duration_seconds=_env_int("WORKFLOW_MAX_DURATION_SECONDS", 86400),
        # ── TRD-CGQ Phase 1: Course Generation Quality ──────────
        generation_provider=os.getenv("AI_GENERATION_PROVIDER", "").lower(),
        template_selector_llm_enabled=_env_bool("AI_TEMPLATE_SELECTOR_LLM_ENABLED", False),
        template_selector_model=os.getenv("AI_TEMPLATE_SELECTOR_MODEL", "qwen2.5:7b"),
        semantic_splitter_enabled=_env_bool("AI_SEMANTIC_SPLITTER_ENABLED", False),
        rules_based_mcq_min_questions=_env_int("AI_RULES_BASED_MCQ_MIN_QUESTIONS", 3),
        component_hierarchy_enabled=_env_bool("AI_COMPONENT_HIERARCHY_ENABLED", False),
        model_escalation_chain=_env_list("AI_MODEL_ESCALATION_CHAIN", ["qwen2.5:7b", "phi3:mini", "mock"]),
    )
    return _ai_config


def get_ai_config() -> AIConfig:
    """Get the global AI configuration singleton.

    Calls load_ai_config() on first access if not yet initialized.
    Thread-safe after initialization (read-only dataclass).
    """
    global _ai_config
    if _ai_config is None:
        _ai_config = load_ai_config()
    return _ai_config


# ── Environment variable helpers ──────────────────────────────

def _env_bool(key: str, default: bool) -> bool:
    """Read a boolean environment variable."""
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes", "enabled")


def _env_int(key: str, default: int) -> int:
    """Read an integer environment variable."""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        logger.warning("Invalid int for %s, using default %d", key, default)
        return default


def _env_float(key: str, default: float) -> float:
    """Read a float environment variable."""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        logger.warning("Invalid float for %s, using default %f", key, default)
        return default


def _env_list(key: str, default: list) -> list:
    """Read a comma-separated list environment variable."""
    raw = os.getenv(key, "")
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]
