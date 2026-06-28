"""
Shared types and enumerations for the MCP client layer.
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class DegradationTier(int, Enum):
    """MCP system degradation tiers — lower = more functional."""
    FULL_MCP = 0       # All MCP servers healthy, provider-agnostic
    GATEWAY_DOWN = 1   # LLM Gateway unavailable, direct backend calls
    ALL_MCP_DOWN = 2   # All MCP servers down, in-process everything
    MOCK_ONLY = 3      # Deterministic mock, zero network


class ProviderHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ToolCallStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"


@dataclass
class MCPToolDef:
    """Discovered MCP tool definition."""
    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)
    server_name: str = ""
    server_url: str = ""


@dataclass
class ProviderInfo:
    """Information about a registered LLM provider backend."""
    name: str
    supported_models: list[str] = field(default_factory=list)
    supports_tool_calling: bool = False
    supports_streaming: bool = False
    health: ProviderHealth = ProviderHealth.UNKNOWN
    tier_affinity: str = ""  # "planner" | "generator" | "both"


@dataclass
class DegradationStatus:
    """Current degradation state of the MCP system."""
    tier: DegradationTier = DegradationTier.FULL_MCP
    llm_gateway_healthy: bool = True
    domain_tools_healthy: bool = True
    active_backends: list[str] = field(default_factory=list)
    degraded_backends: list[str] = field(default_factory=list)
    last_transition_at: float = 0.0
    circuit_breakers_open: list[str] = field(default_factory=list)
