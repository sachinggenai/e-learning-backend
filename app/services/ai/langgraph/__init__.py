"""LangGraph orchestration for course generation — Phase 2.1-2.3.

Provides the multi-agent StateGraph that orchestrates the full course
generation pipeline with parallel fan-out, HITL interrupts, and
PostgreSQL-backed checkpointing.

Graceful degradation: when LangGraph is not installed, the existing
WorkflowOrchestrator handles course generation sequentially.
"""
