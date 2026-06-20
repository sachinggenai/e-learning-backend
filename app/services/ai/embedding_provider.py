"""Embedding provider abstraction — US-BKND-AI-015.

Pluggable interface for generating text embeddings.
    - MockEmbeddingProvider: Deterministic hash-based, zero-cost, zero-network. Dev/QA.
    - OpenAIBackend: text-embedding-ada-002 via OpenAI SDK. Production.

Factory: get_embedding_provider() — controlled by EMBEDDING_PROVIDER env var.
"""
from __future__ import annotations

import hashlib
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger("ai_authoring")

DEFAULT_EMBEDDING_DIMENSION = 1536
MAX_EMBEDDING_INPUT_CHARS = 8191  # ada-002 token limit (~6000 words)


class EmbeddingProvider(ABC):
    """Abstract interface for text → vector conversion."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Convert text to embedding vector. Raises EmbeddingError on failure."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding vector dimension."""
        ...


class EmbeddingError(Exception):
    """Wraps provider-specific errors for uniform handling upstream."""

    def __init__(self, message: str, provider: str, retryable: bool = True):
        self.provider = provider
        self.retryable = retryable
        super().__init__(f"[{provider}] {message}")


# ── OpenAI Backend ────────────────────────────────────────────────────

class OpenAIBackend(EmbeddingProvider):
    """OpenAI text-embedding-ada-002 production backend.

    Prerequisites:
        - pip install openai
        - OPENAI_API_KEY env var set
        - EMBEDDING_MODEL env var (default: text-embedding-ada-002)

    Error handling:
        - AuthenticationError (401) → EmbeddingError(retryable=False)
        - RateLimitError (429) → EmbeddingError(retryable=True)
        - APITimeoutError → EmbeddingError(retryable=True)
        - All other API errors → EmbeddingError(retryable=True)
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._model = model or os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")
        self._dimension = DEFAULT_EMBEDDING_DIMENSION
        self._client = None

    @property
    def dimension(self) -> int:
        return self._dimension

    def _get_client(self):
        """Lazy-init the OpenAI client (avoids import if using mock provider)."""
        if self._client is None:
            try:
                import openai
                self._client = openai.AsyncOpenAI(api_key=self._api_key)
            except ImportError:
                raise EmbeddingError(
                    "openai package not installed. Run: pip install openai",
                    provider="openai",
                    retryable=False,
                )
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Generate embedding via OpenAI API.

        Non-retryable failures: missing API key, bad API key (401).
        Retryable failures: rate limit (429), timeout, connection error.
        """
        if not self._api_key:
            raise EmbeddingError(
                "OPENAI_API_KEY is not set", provider="openai", retryable=False
            )

        client = self._get_client()
        truncated = text[:MAX_EMBEDDING_INPUT_CHARS]

        try:
            resp = await client.embeddings.create(
                model=self._model, input=truncated,
            )
            return resp.data[0].embedding
        except Exception as exc:
            # Distinguish retryable vs non-retryable OpenAI errors
            exc_name = type(exc).__name__
            non_retryable = any(
                tag in exc_name.lower()
                for tag in ("authentication", "permission", "notfound")
            )
            logger.error("OpenAI embedding failed [%s]: %s", exc_name, exc)
            raise EmbeddingError(
                str(exc), provider="openai", retryable=not non_retryable,
            ) from exc


# ── Mock Backend ───────────────────────────────────────────────────────

class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic mock for development and testing.

    Generates a pseudo-embedding from SHA-256 of the input text.
    Same input → same vector. Different inputs → different vectors.
    Zero external dependencies, zero cost, zero network latency.
    """

    def __init__(self, dimension: int = DEFAULT_EMBEDDING_DIMENSION):
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        """Deterministic pseudo-embedding from text hash."""
        h = hashlib.sha256(text.encode("utf-8")).digest()
        vec = []
        for i in range(self._dimension):
            base = h[i % len(h)] / 255.0
            offset = i * 0.0174533  # π/180 radians
            vec.append(round(base * 0.5 + 0.25, 8))
        return vec


# ── Factory (singleton) ────────────────────────────────────────────────

_embedding_provider: Optional[EmbeddingProvider] = None


def get_embedding_provider() -> EmbeddingProvider:
    """Return the configured embedding provider (singleton).

    Controlled by EMBEDDING_PROVIDER env var:
        "openai" → OpenAIBackend (requires OPENAI_API_KEY)
        "mock" or unset → MockEmbeddingProvider (deterministic, zero-cost)
    """
    global _embedding_provider
    if _embedding_provider is not None:
        return _embedding_provider

    provider_name = os.getenv("EMBEDDING_PROVIDER", "mock").lower()
    if provider_name == "openai":
        _embedding_provider = OpenAIBackend()
        logger.info("Embedding provider: OpenAI (%s)", _embedding_provider._model)
    else:
        _embedding_provider = MockEmbeddingProvider()
        logger.info(
            "Embedding provider: Mock (deterministic, %d-dim)",
            _embedding_provider.dimension,
        )

    return _embedding_provider
