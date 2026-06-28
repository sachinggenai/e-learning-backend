"""
LLM Gateway MCP Server configuration.

Loads provider backend configurations from environment variables.
Controls which backends are registered at startup.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GatewayConfig:
    """Configuration for the LLM Gateway MCP Server."""

    # Server
    host: str = "127.0.0.1"
    port: int = 8004
    log_level: str = "info"

    # Provider activation (comma-separated list, or "all")
    enabled_providers: str = "mock,anthropic,ollama"

    # Default provider for fallback
    default_provider: str = "mock"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = ""

    # Ollama
    ollama_base_url: str = "http://localhost:11434"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    # LiteLLM meta-backend
    litellm_enabled: bool = False

    # Health
    health_check_interval_seconds: int = 30

    # Misc
    metadata: Dict[str, str] = field(default_factory=dict)


def load_gateway_config() -> GatewayConfig:
    """Load gateway configuration from environment variables."""
    return GatewayConfig(
        host=os.getenv("MCP_LLM_GATEWAY_HOST", "127.0.0.1"),
        port=_env_int("MCP_LLM_GATEWAY_PORT", 8004),
        log_level=os.getenv("MCP_LLM_GATEWAY_LOG_LEVEL", "info"),
        enabled_providers=os.getenv("LLM_PROVIDER_LIST", "mock,anthropic,ollama"),
        default_provider=os.getenv("LLM_PROVIDER", "mock"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN", ""),
        anthropic_base_url=os.getenv("ANTHROPIC_BASE_URL", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_base_url=os.getenv("OPENAI_BASE_URL", ""),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        litellm_enabled=_env_bool("LITELLM_ENABLED", False),
        health_check_interval_seconds=_env_int(
            "MCP_LLM_GATEWAY_HEALTH_CHECK_INTERVAL", 30
        ),
    )


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes", "enabled")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default
