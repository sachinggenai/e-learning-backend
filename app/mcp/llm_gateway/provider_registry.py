"""
Dynamic Provider Registry for LLM Gateway.

Thread-safe registry for LLM backends. Supports:
- Register/unregister backends at runtime
- Lookup by provider name or model name
- Model tier resolution (PLANNER vs GENERATOR)
- Health tracking per provider
"""

from __future__ import annotations

import logging
from threading import Lock
from typing import Dict, List, Optional, Tuple

from app.services.ai.mcp_client.types import ProviderHealth, ProviderInfo
from app.mcp.llm_gateway.backends.base import LLMBackend

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Thread-safe registry of LLM provider backends.

    Usage:
        registry = ProviderRegistry()
        registry.register(MockBackend())
        registry.register(AnthropicBackend())

        backend = registry.get_backend("anthropic")
        response = await backend.chat(request)

        provider, model = registry.resolve_model_for_tier(
            ModelTier.PLANNER,
            preferred_provider="ollama",
            preferred_model="phi3:mini",
        )
    """

    def __init__(self):
        self._lock = Lock()
        self._backends: Dict[str, LLMBackend] = {}
        # Model name → provider name index
        self._model_index: Dict[str, str] = {}
        # Tier affinity: provider → "planner"|"generator"|"both"
        self._tier_affinity: Dict[str, str] = {}
        # Per-provider health state
        self._health: Dict[str, ProviderHealth] = {}

    # ── Registration ────────────────────────────────────────

    def register(self, backend: LLMBackend) -> None:
        """Register a provider backend.

        If a backend with the same provider_name already exists,
        it is replaced.
        """
        with self._lock:
            name = backend.provider_name
            self._backends[name] = backend

            # Index all supported models
            for model in backend.supported_models:
                self._model_index[model] = name

            # Default tier affinity
            self._tier_affinity[name] = self._infer_tier_affinity(name)
            self._health[name] = ProviderHealth.UNKNOWN

            logger.info(
                "Registered provider '%s' with %d models: %s",
                name,
                len(backend.supported_models),
                backend.supported_models,
            )

    def unregister(self, provider_name: str) -> bool:
        """Remove a provider backend. Returns True if it existed."""
        with self._lock:
            if provider_name not in self._backends:
                return False
            del self._backends[provider_name]
            # Clean model index
            stale = [m for m, p in self._model_index.items() if p == provider_name]
            for model in stale:
                del self._model_index[model]
            self._tier_affinity.pop(provider_name, None)
            self._health.pop(provider_name, None)
            logger.info("Unregistered provider '%s'", provider_name)
            return True

    # ── Lookup ──────────────────────────────────────────────

    def get_backend(self, provider_name: str) -> Optional[LLMBackend]:
        """Get a backend by provider name."""
        return self._backends.get(provider_name)

    def get_backend_for_model(self, model_name: str) -> Optional[LLMBackend]:
        """Find which backend handles a given model name."""
        provider_name = self._model_index.get(model_name)
        if provider_name:
            return self._backends.get(provider_name)
        return None

    def resolve_model(
        self,
        model_name: str,
        preferred_provider: str = "",
    ) -> Tuple[Optional[str], Optional[LLMBackend]]:
        """Resolve a model name to (provider_name, backend).

        If the model is found in the index, returns that backend.
        Otherwise falls back to the preferred_provider.
        """
        # Exact match in index
        provider_name = self._model_index.get(model_name)
        if provider_name and provider_name in self._backends:
            return provider_name, self._backends[provider_name]

        # Preferred provider
        if preferred_provider and preferred_provider in self._backends:
            return preferred_provider, self._backends[preferred_provider]

        # First available healthy backend
        for name, backend in self._backends.items():
            if self._health.get(name) != ProviderHealth.UNHEALTHY:
                return name, backend

        # Any backend
        for name, backend in self._backends.items():
            return name, backend

        return None, None

    def resolve_model_for_tier(
        self,
        tier: str,  # "planner" | "generator"
        preferred_provider: str = "",
        preferred_model: str = "",
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolve best (provider_name, model_name) for a model tier.

        Resolution order:
        1. Explicitly preferred model (if its provider is registered)
        2. Preferred provider with tier affinity
        3. Any provider with tier affinity
        4. First healthy provider
        """
        # 1. Explicit model
        if preferred_model:
            provider_name = self._model_index.get(preferred_model)
            if provider_name and provider_name in self._backends:
                return provider_name, preferred_model

        # 2. Preferred provider
        if (
            preferred_provider
            and preferred_provider in self._backends
            and self._health.get(preferred_provider) != ProviderHealth.UNHEALTHY
        ):
            return preferred_provider, self._pick_model(preferred_provider, tier)

        # 3. Any provider with matching tier affinity
        for name, backend in self._backends.items():
            affinity = self._tier_affinity.get(name, "both")
            if affinity in (tier, "both"):
                if self._health.get(name) != ProviderHealth.UNHEALTHY:
                    return name, self._pick_model(name, tier)

        # 4. First healthy provider
        for name, backend in self._backends.items():
            if self._health.get(name) != ProviderHealth.UNHEALTHY:
                return name, self._pick_model(name, tier)

        return None, None

    # ── Listing ──────────────────────────────────────────────

    def list_backends(self) -> List[LLMBackend]:
        """Return all registered backends."""
        return list(self._backends.values())

    def list_provider_infos(self) -> List[ProviderInfo]:
        """Return provider info summaries."""
        return [
            ProviderInfo(
                name=name,
                supported_models=backend.supported_models,
                supports_tool_calling=backend.supports_tool_calling,
                supports_streaming=backend.supports_streaming,
                health=self._health.get(name, ProviderHealth.UNKNOWN),
                tier_affinity=self._tier_affinity.get(name, "both"),
            )
            for name, backend in self._backends.items()
        ]

    def list_models(self) -> Dict[str, List[str]]:
        """Return {provider_name: [model_names]}."""
        return {
            name: backend.supported_models
            for name, backend in self._backends.items()
        }

    # ── Health ───────────────────────────────────────────────

    def update_health(self, provider_name: str, health: ProviderHealth) -> None:
        """Update the health status of a provider."""
        with self._lock:
            old = self._health.get(provider_name)
            if old != health:
                self._health[provider_name] = health
                logger.info(
                    "Provider '%s' health: %s → %s",
                    provider_name,
                    old,
                    health,
                )

    def get_health(self, provider_name: str) -> ProviderHealth:
        """Get current health of a provider."""
        return self._health.get(provider_name, ProviderHealth.UNKNOWN)

    def check_all_health(self) -> Dict[str, ProviderHealth]:
        """Check health of all registered backends (async)."""
        import asyncio

        async def _check():
            results = {}
            for name, backend in list(self._backends.items()):
                try:
                    health = await backend.health()
                except Exception:
                    health = ProviderHealth.UNHEALTHY
                self.update_health(name, health)
                results[name] = health
            return results

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, create a task
                import asyncio
                future = asyncio.ensure_future(_check())
                # Can't await here; health is updated eventually
                return dict(self._health)
            else:
                return loop.run_until_complete(_check())
        except RuntimeError:
            return dict(self._health)

    async def check_all_health_async(self) -> Dict[str, ProviderHealth]:
        """Async version: check health of all backends."""
        for name, backend in list(self._backends.items()):
            try:
                health = await backend.health()
            except Exception:
                health = ProviderHealth.UNHEALTHY
            self.update_health(name, health)
        return dict(self._health)

    # ── Helpers ──────────────────────────────────────────────

    def _infer_tier_affinity(self, provider_name: str) -> str:
        """Infer the tier affinity from provider name."""
        planner_providers = {"mock"}
        generator_providers = {"anthropic", "openai", "deepseek"}
        both_providers = {"ollama"}
        if provider_name in planner_providers:
            return "planner"
        if provider_name in generator_providers:
            return "generator"
        if provider_name in both_providers:
            return "both"
        return "both"

    def _pick_model(self, provider_name: str, tier: str) -> str:
        """Pick the best model from a provider for a tier."""
        backend = self._backends.get(provider_name)
        if not backend or not backend.supported_models:
            return "default"

        models = backend.supported_models
        # Prefer models with tier-relevant names
        tier_hints = {
            "planner": ["mini", "flash", "haiku", "planner"],
            "generator": ["pro", "sonnet", "opus", "generator"],
        }
        hints = tier_hints.get(tier, [])
        for model in models:
            for hint in hints:
                if hint in model.lower():
                    return model
        return models[0]
