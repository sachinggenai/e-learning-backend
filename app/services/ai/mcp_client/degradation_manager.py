"""
Degradation Manager — circuit breaker and fallback tier management.

Manages the 4-tier degradation system:
- Tier 0: Full MCP (all servers healthy)
- Tier 1: Gateway down (direct backend calls)
- Tier 2: All MCP down (in-process everything)
- Tier 3: Mock only (deterministic, zero network)
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from app.services.ai.mcp_client.types import DegradationTier, DegradationStatus

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Simple circuit breaker per MCP server."""

    def __init__(self, name: str, threshold: int = 3, reset_seconds: float = 30.0):
        self.name = name
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._open = False
        self._opened_at = 0.0

    @property
    def is_open(self) -> bool:
        """Is the circuit currently open (server considered down)?"""
        if not self._open:
            return False
        # Check if it's time to try half-open
        if time.time() - self._opened_at >= self.reset_seconds:
            self._open = False
            logger.info("Circuit '%s' transitioning to HALF-OPEN", self.name)
            return False
        return True

    def record_success(self) -> None:
        """Record a successful call."""
        self._failure_count = 0
        if self._open:
            logger.info("Circuit '%s' CLOSED (healthy again)", self.name)
        self._open = False

    def record_failure(self) -> None:
        """Record a failed call. Opens circuit if threshold exceeded."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.threshold:
            if not self._open:
                logger.warning(
                    "Circuit '%s' OPEN after %d failures",
                    self.name,
                    self._failure_count,
                )
            self._open = True
            self._opened_at = time.time()

    def reset(self) -> None:
        """Force-reset the circuit breaker."""
        self._failure_count = 0
        self._open = False


class DegradationManager:
    """Manages MCP system degradation with circuit breakers per server."""

    def __init__(self):
        self._current_tier = DegradationTier.FULL_MCP
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._last_transition_time = time.time()

    @property
    def current_tier(self) -> DegradationTier:
        return self._current_tier

    @property
    def open_circuits(self) -> List[str]:
        """List of servers with open circuit breakers."""
        return [name for name, cb in self._circuit_breakers.items() if cb.is_open]

    def get_circuit(self, server_name: str) -> CircuitBreaker:
        """Get or create a circuit breaker for a server."""
        if server_name not in self._circuit_breakers:
            self._circuit_breakers[server_name] = CircuitBreaker(server_name)
        return self._circuit_breakers[server_name]

    def record_success(self, server_name: str) -> None:
        """Record a successful call to a server."""
        cb = self.get_circuit(server_name)
        cb.record_success()
        self._recalculate_tier()

    def record_failure(self, server_name: str) -> None:
        """Record a failed call to a server."""
        cb = self.get_circuit(server_name)
        cb.record_failure()
        self._recalculate_tier()

    def is_server_available(self, server_name: str) -> bool:
        """Check if a server is considered available."""
        cb = self._circuit_breakers.get(server_name)
        if cb is None:
            return True  # Never tried = assume available
        return not cb.is_open

    def set_tier(self, tier: DegradationTier) -> None:
        """Explicitly set the degradation tier."""
        if tier != self._current_tier:
            logger.info(
                "Degradation tier: %s → %s",
                self._current_tier.name,
                tier.name,
            )
            self._current_tier = tier
            self._last_transition_time = time.time()

    def _recalculate_tier(self) -> None:
        """Recalculate tier based on circuit breaker states."""
        all_open = all(
            cb.is_open for cb in self._circuit_breakers.values()
        ) if self._circuit_breakers else False

        any_open = any(
            cb.is_open for cb in self._circuit_breakers.values()
        )

        if not any_open:
            new_tier = DegradationTier.FULL_MCP
        elif all_open:
            new_tier = DegradationTier.ALL_MCP_DOWN
        else:
            new_tier = DegradationTier.GATEWAY_DOWN

        self.set_tier(new_tier)

    def get_status(self) -> DegradationStatus:
        """Get the current degradation status."""
        return DegradationStatus(
            tier=self._current_tier,
            llm_gateway_healthy=self.is_server_available("llm-gateway"),
            domain_tools_healthy=self.is_server_available("domain-tools"),
            circuit_breakers_open=self.open_circuits,
            last_transition_at=self._last_transition_time,
        )
