"""
LLM Gateway provider backends.

Each backend implements the LLMBackend ABC, translating between
the canonical ChatCompletionRequest/Response format and the
provider-specific API protocol.
"""

from app.mcp.llm_gateway.backends.base import LLMBackend
from app.mcp.llm_gateway.backends.mock_backend import MockBackend
from app.mcp.llm_gateway.backends.anthropic_backend import AnthropicBackend
from app.mcp.llm_gateway.backends.ollama_backend import OllamaBackend

__all__ = ["LLMBackend", "MockBackend", "AnthropicBackend", "OllamaBackend"]
