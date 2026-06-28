"""
MCP Client Manager — singleton lifecycle manager for all MCP connections.

Manages:
- LLM Gateway connection (HTTP to port 8004 or in-process fallback)
- Heartbeat monitoring with auto-reconnection
- Degradation tier escalation
- Integration with FastAPI lifespan

All connections are optional — the system degrades gracefully
when MCP servers are not running.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.services.ai.mcp_client.types import (
    DegradationTier,
    DegradationStatus,
    ProviderHealth,
)
from app.services.ai.mcp_client.llm_gateway_client import LLMGatewayClient
from app.services.ai.mcp_client.domain_tool_client import DomainToolClient
from app.services.ai.mcp_client.degradation_manager import DegradationManager
from app.services.ai.mcp_client.tool_registry import ToolRegistry

logger = logging.getLogger("mcp-client-manager")

# Default gateway URL (can be overridden via env)
DEFAULT_GATEWAY_URL = "http://localhost:8004"
DEFAULT_DOMAIN_TOOL_URL = "http://localhost:8005"


class MCPClientManager:
    """Singleton manager for MCP client lifecycle.

    Usage:
        manager = MCPClientManager.get_instance()

        # In FastAPI lifespan:
        await manager.start()
        ...
        await manager.stop()

        # Anywhere in the app:
        client = await manager.get_llm_gateway()
        response = await client.chat(request)
    """

    _instance: Optional["MCPClientManager"] = None

    def __init__(
        self,
        gateway_url: str = "",
        domain_tool_url: str = "",
    ):
        import os

        self.gateway_url = gateway_url or os.getenv(
            "MCP_LLM_GATEWAY_URL", DEFAULT_GATEWAY_URL
        )
        self.domain_tool_url = domain_tool_url or os.getenv(
            "MCP_DOMAIN_TOOL_URL", DEFAULT_DOMAIN_TOOL_URL
        )

        # Clients (initialized in start())
        self._llm_gateway: Optional[LLMGatewayClient] = None
        self._domain_tools: Optional[DomainToolClient] = None

        # Subsystems
        self._degradation = DegradationManager()
        self._tool_registry = ToolRegistry()

        # Lifecycle
        self._started = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_interval = int(
            os.getenv("MCP_HEARTBEAT_INTERVAL", "15")
        )

    @classmethod
    def get_instance(cls) -> "MCPClientManager":
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset singleton (for testing)."""
        cls._instance = None

    # ── Lifecycle ──────────────────────────────────────────

    async def start(self) -> None:
        """Start all MCP connections.

        Called once during application startup.
        Does NOT crash if MCP servers are unavailable — degrades gracefully.
        """
        if self._started:
            return

        logger.info("Starting MCP Client Manager...")
        self._started = True

        # Initialize clients
        self._llm_gateway = LLMGatewayClient(base_url=self.gateway_url)
        self._domain_tools = DomainToolClient(base_url=self.domain_tool_url)

        # Check initial connectivity
        await self._check_connectivity()

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        tier = self._degradation.current_tier
        status = self.get_degradation_status()
        logger.info(
            "MCP Client Manager started. Tier: %d (%s). "
            "LLM Gateway: %s, Domain Tools: %s",
            tier.value,
            tier.name,
            "healthy" if status.llm_gateway_healthy else "unavailable",
            "healthy" if status.domain_tools_healthy else "unavailable",
        )

    async def stop(self) -> None:
        """Stop all MCP connections gracefully.

        Called during application shutdown.
        """
        if not self._started:
            return

        logger.info("Stopping MCP Client Manager...")

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        # Close clients
        if self._llm_gateway:
            await self._llm_gateway.close()
            self._llm_gateway = None
        if self._domain_tools:
            await self._domain_tools.close()
            self._domain_tools = None

        self._started = False
        logger.info("MCP Client Manager stopped.")

    # ── Client Access ──────────────────────────────────────

    async def get_llm_gateway(self) -> LLMGatewayClient:
        """Get the LLM Gateway client.

        Always returns a client — even if the gateway is down,
        the client returns error responses rather than throwing.
        """
        if not self._started:
            await self.start()
        return self._llm_gateway

    async def get_domain_tools(self) -> DomainToolClient:
        """Get the Domain Tools client."""
        if not self._started:
            await self.start()
        return self._domain_tools

    @property
    def degradation(self) -> DegradationManager:
        return self._degradation

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    # ── Status ─────────────────────────────────────────────

    def get_degradation_status(self) -> DegradationStatus:
        """Get the current MCP system degradation status."""
        gw_healthy = (
            self._llm_gateway is not None
            and self._llm_gateway.is_healthy
        )
        dt_healthy = (
            self._domain_tools is not None
            and self._domain_tools.is_healthy
        )

        return DegradationStatus(
            tier=self._degradation.current_tier,
            llm_gateway_healthy=gw_healthy,
            domain_tools_healthy=dt_healthy,
            circuit_breakers_open=self._degradation.open_circuits,
        )

    @property
    def is_gateway_available(self) -> bool:
        """Quick check: is the LLM Gateway reachable?"""
        return (
            self._llm_gateway is not None
            and self._llm_gateway.is_healthy
        )

    # ── Internal ───────────────────────────────────────────

    async def _check_connectivity(self) -> None:
        """Check connectivity to all MCP servers."""
        checks = []

        if self._llm_gateway:
            checks.append(self._llm_gateway.check_health())

        if self._domain_tools:
            checks.append(self._domain_tools.check_health())

        if checks:
            results = await asyncio.gather(*checks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning("MCP health check failed: %s", result)

        self._update_degradation_tier()

    def _update_degradation_tier(self) -> DegradationTier:
        """Update the degradation tier based on current health.

        LLM Gateway is the critical path — domain tools are optional.
        Tier decisions prioritize gateway availability.
        """
        gw_healthy = self.is_gateway_available
        dt_healthy = (
            self._domain_tools is not None
            and self._domain_tools.is_healthy
        )

        if gw_healthy:
            # Gateway is up — LLM operations work. Domain tools
            # being down only affects tool execution, not chat.
            tier = DegradationTier.FULL_MCP
        elif dt_healthy:
            # Gateway down but domain tools up — unusual but possible
            tier = DegradationTier.GATEWAY_DOWN
        else:
            # Nothing MCP is available
            tier = DegradationTier.ALL_MCP_DOWN

        self._degradation.set_tier(tier)
        return tier

    async def _heartbeat_loop(self) -> None:
        """Periodic health check loop."""
        while True:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                await self._check_connectivity()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Heartbeat check failed")
