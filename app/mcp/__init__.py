"""MCP Tool Servers — Phase 3.1-3.3.

3 independently deployable MCP (Model Context Protocol) servers:
    - content-writer-mcp: LLM content generation with independent scaling
    - safety-scan-mcp: Input/output/PII scanning with future NeMo integration
    - template-registry-mcp: Template schema retrieval with independent updates

Each server is a standalone FastAPI app that can be deployed separately
or co-located with the main application.

Architecture:
    Main App → HTTP/MCP → MCP Server → Existing Service

When MCP servers are unavailable, the main app falls back to in-process
service calls (graceful degradation).
"""
