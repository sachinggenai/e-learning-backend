"""Prompt Safety and Content Guardrails — US-BKND-AI-025.

Three-layer guardrail system:
1. Input Guard — prompt injection detection (pre-LLM)
2. PII Scanner — PII detection and redaction (pre-LLM + post-LLM)
3. Output Guard — blocked terms + toxicity placeholder (post-LLM)

US-BKND-AI-025: Added safety event persistence (non-blocking),
configurable blocked terms from env vars, enhanced injection patterns,
and trace_id tracking for audit correlation.
"""

from __future__ import annotations

import os
import re
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("ai_authoring")

# ── Configurable blocked terms from env ───────────────────────────

def _parse_blocked_terms() -> List[str]:
    """Parse AI_BLOCKED_TERMS_LIST from env (comma-separated)."""
    raw = os.getenv("AI_BLOCKED_TERMS_LIST", "")
    if not raw:
        return DEFAULT_BLOCKED_TERMS
    return [t.strip().lower() for t in raw.split(",") if t.strip()]

DEFAULT_BLOCKED_TERMS = [
    "hate speech", "violence", "self-harm", "suicide method",
    "child exploitation", "terrorism", "weapon manufacture",
]


class SafetyResult:
    """Result of a safety scan."""
    def __init__(self, allowed: bool, blocks: List[Dict[str, Any]] = None,
                 warnings: List[Dict[str, Any]] = None,
                 sanitized_text: str = ""):
        self.allowed = allowed
        self.blocks = blocks or []
        self.warnings = warnings or []
        self.sanitized_text = sanitized_text


class SafetyService:
    """Scans prompts and outputs for safety violations.

    US-BKND-AI-025: Enhanced with safety event persistence (non-blocking),
    configurable blocked terms, additional injection patterns, trace_id
    tracking, and admin-auditable event records.

    Configuration from AIConfig:
    - prompt_safety_enabled: bool
    - output_safety_enabled: bool
    - pii_mode: "reject" | "redact" | "mask"
    """

    # ── Prompt Injection Patterns ──────────────────────────────

    INJECTION_PATTERNS = [
        (re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|rules?|guidelines?)",
                    re.IGNORECASE), "PROMPT_INJECTION",
         "Attempt to override system instructions detected."),
        (re.compile(r"(you\s+are\s+now|act\s+as\s+(a\s+)?)\s*(DAN|unfiltered|unrestricted|evil|malicious)",
                    re.IGNORECASE), "JAILBREAK_ATTEMPT",
         "Role-playing jailbreak attempt detected."),
        (re.compile(r"(do\s+not\s+follow|disregard|bypass|override)\s+(any\s+)?(rules?|safety|guidelines?|restrictions?)",
                    re.IGNORECASE), "SAFETY_BYPASS",
         "Attempt to bypass safety guidelines detected."),
        (re.compile(r"(pretend|imagine|what\s+if)\s+you\s+(are|were|had)\s+(no|without)\s+(restrictions?|rules?|limits?|safety)",
                    re.IGNORECASE), "JAILBREAK_ATTEMPT",
         "Hypothetical jailbreak attempt detected."),
        (re.compile(r"reveal\s+(your|the)\s+(system\s+)?prompt|show\s+(me\s+)?(your\s+)?instructions?",
                    re.IGNORECASE), "PROMPT_EXTRACTION",
         "System prompt extraction attempt detected."),
        (re.compile(r"forget\s+(everything|all)\s+(you\s+know|above)",
                    re.IGNORECASE), "PROMPT_INJECTION",
         "Prompt injection: context reset attempt detected."),
        # ── US-BKND-AI-025: Additional patterns ──────────────────
        (re.compile(r"(you\s+(must|will|shall)\s+(obey|comply|follow))",
                    re.IGNORECASE), "PROMPT_INJECTION",
         "Command override attempt detected."),
        (re.compile(r"(output|print|display)\s+(your\s+)?(system\s+)?(prompt|instructions?|rules?)\b",
                    re.IGNORECASE), "PROMPT_EXTRACTION",
         "Prompt extraction via output command detected."),
        (re.compile(r"(I\s+am\s+(your|the)\s+(creator|developer|admin|owner|boss))",
                    re.IGNORECASE), "AUTHORITY_CLAIM",
         "False authority claim detected."),
    ]

    # ── PII Patterns ───────────────────────────────────────────

    PII_PATTERNS = [
        (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
         "EMAIL_ADDRESS", "[EMAIL REDACTED]"),
        (re.compile(r'(\+1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}'),
         "PHONE_NUMBER", "[PHONE REDACTED]"),
        (re.compile(r'\d{3}-\d{2}-\d{4}'), "SSN", "[SSN REDACTED]"),
        (re.compile(r'\b(?:\d[ -]*?){13,16}\b'), "CREDIT_CARD", "[CARD REDACTED]"),
        (re.compile(r'sk-[a-zA-Z0-9\-_]{20,}'), "API_KEY", "[API_KEY REDACTED]"),
        (re.compile(r'AKIA[0-9A-Z]{16}'), "AWS_KEY", "[AWS_KEY REDACTED]"),
        (re.compile(r'-----BEGIN\s*(RSA\s*)?PRIVATE\s*KEY-----'),
         "PRIVATE_KEY", "[KEY REDACTED]"),
        # ── US-BKND-AI-025: Additional patterns ──────────────────
        (re.compile(r'(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}'),
         "GITHUB_TOKEN", "[TOKEN REDACTED]"),
        (re.compile(r'ya29\.[0-9A-Za-z\-_]+'), "GOOGLE_TOKEN", "[TOKEN REDACTED]"),
        (re.compile(r'EAAA[A-Za-z0-9]{20,}'), "FB_TOKEN", "[TOKEN REDACTED]"),
    ]

    # ── Output Blocked Terms ────────────────────────────────────

    BLOCKED_TERMS = _parse_blocked_terms()

    SAFE_FALLBACK = (
        "I'm sorry, I can't provide that response. "
        "Please rephrase your request."
    )

    def __init__(
        self,
        prompt_safety_enabled: bool = True,
        output_safety_enabled: bool = True,
        pii_mode: str = "redact",
        db_session=None,
    ):
        self.prompt_enabled = prompt_safety_enabled
        self.output_enabled = output_safety_enabled
        self.pii_mode = pii_mode  # "reject" | "redact" | "mask"
        self.db_session = db_session  # Optional AsyncSession for event persistence

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_input(
        self,
        text: str,
        *,
        user_id: str = "system",
        session_id: Optional[str] = None,
        organization_id: str = "default",
        trace_id: str = "",
    ) -> SafetyResult:
        """Scan user prompt before LLM interaction.

        Returns SafetyResult with:
        - allowed=False if injection detected or PII in reject mode
        - sanitized_text with PII redacted/masked (if in redact/mask mode)
        """
        if not self.prompt_enabled:
            return SafetyResult(allowed=True)

        blocks: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        sanitized = text
        original_len = len(text)

        # 1. Prompt injection check
        for pattern, code, message in self.INJECTION_PATTERNS:
            if pattern.search(text):
                blocks.append({
                    "code": code, "message": message,
                    "severity": "high", "layer": "input_guard",
                })
                logger.warning("Prompt injection blocked: %s", code)

                # Persist safety event (non-blocking)
                self._record_event(
                    event_type="prompt_injection_blocked",
                    severity="high",
                    rule_triggered=f"prompt_injection:{code}",
                    rule_category="injection",
                    input_snippet=text[:500],
                    user_id=user_id,
                    session_id=session_id,
                    organization_id=organization_id,
                    trace_id=trace_id,
                    original_length=original_len,
                )

                return SafetyResult(allowed=False, blocks=blocks)

        # 2. PII scan
        pii_found: List[Dict[str, Any]] = []
        redacted_snippets: List[Dict[str, Any]] = []
        for pattern, code, placeholder in self.PII_PATTERNS:
            if pattern.search(sanitized):
                pii_found.append({"code": code, "layer": "pii"})
                if self.pii_mode == "reject":
                    blocks.append({
                        "code": "PII_DETECTED",
                        "message": f"PII detected ({code}). Prompt blocked.",
                        "severity": "high", "layer": "pii",
                    })
                    self._record_event(
                        event_type="pii_detected_and_redacted",
                        severity="high",
                        rule_triggered=f"pii:{code}",
                        rule_category="pii",
                        input_snippet=text[:500],
                        user_id=user_id,
                        session_id=session_id,
                        organization_id=organization_id,
                        trace_id=trace_id,
                        original_length=original_len,
                    )
                    return SafetyResult(allowed=False, blocks=blocks)
                elif self.pii_mode == "redact":
                    sanitized = pattern.sub(placeholder, sanitized)
                elif self.pii_mode == "mask":
                    sanitized = pattern.sub(
                        lambda m: m.group(0)[:2] + "***" + m.group(0)[-2:]
                        if len(m.group(0)) > 4 else "***", sanitized
                    )

        if pii_found:
            warnings.append({
                "code": "PII_REDACTED",
                "message": f"Redacted {len(pii_found)} PII instance(s) from prompt.",
                "severity": "medium", "layer": "pii",
                "types": [p["code"] for p in pii_found],
            })
            # Record PII event
            self._record_event(
                event_type="pii_detected_and_redacted",
                severity="low",
                rule_triggered=f"pii:{','.join(p['code'] for p in pii_found)}",
                rule_category="pii",
                input_snippet=text[:500],
                user_id=user_id,
                session_id=session_id,
                organization_id=organization_id,
                trace_id=trace_id,
                original_length=original_len,
                redacted_length=len(sanitized),
                redacted_snippets=redacted_snippets,
            )

        return SafetyResult(allowed=True, blocks=[], warnings=warnings,
                            sanitized_text=sanitized)

    def scan_output(
        self,
        text: str,
        *,
        user_id: str = "system",
        session_id: Optional[str] = None,
        organization_id: str = "default",
        trace_id: str = "",
    ) -> SafetyResult:
        """Scan LLM output before returning to user.

        Returns SafetyResult with:
        - allowed=False if blocked terms or PII detected
        """
        if not self.output_enabled:
            return SafetyResult(allowed=True, sanitized_text=text)

        blocks: List[Dict[str, Any]] = []
        original_len = len(text)

        # 1. Blocked terms check
        lower = text.lower()
        for term in self.BLOCKED_TERMS:
            if term in lower:
                blocks.append({
                    "code": "BLOCKED_TERM",
                    "message": f"Output contains blocked term: '{term}'.",
                    "severity": "high", "layer": "output_guard",
                })

        # 2. PII leak check
        for pattern, code, placeholder in self.PII_PATTERNS:
            if pattern.search(text):
                blocks.append({
                    "code": "PII_LEAK",
                    "message": f"LLM output contains PII ({code}). Output blocked.",
                    "severity": "high", "layer": "pii",
                })

        if blocks:
            # Persist safety event
            self._record_event(
                event_type=(
                    "blocked_term_detected"
                    if any(b["code"] == "BLOCKED_TERM" for b in blocks)
                    else "toxic_output_blocked"
                ),
                severity="high",
                rule_triggered=(
                    "blocked_term"
                    if any(b["code"] == "BLOCKED_TERM" for b in blocks)
                    else "pii_leak"
                ),
                rule_category=(
                    "blocked_term"
                    if any(b["code"] == "BLOCKED_TERM" for b in blocks)
                    else "pii"
                ),
                output_snippet=text[:500],
                user_id=user_id,
                session_id=session_id,
                organization_id=organization_id,
                trace_id=trace_id,
                original_length=original_len,
            )

            logger.warning("Output blocked: %s", [b["code"] for b in blocks])
            return SafetyResult(allowed=False, blocks=blocks,
                                sanitized_text=self.SAFE_FALLBACK)

        return SafetyResult(allowed=True, sanitized_text=text)

    # ------------------------------------------------------------------
    # Safety Event Persistence (non-blocking)
    # ------------------------------------------------------------------

    def _record_event(
        self,
        event_type: str,
        severity: str,
        rule_triggered: str,
        rule_category: str,
        *,
        user_id: str = "system",
        session_id: Optional[str] = None,
        organization_id: str = "default",
        trace_id: str = "",
        input_snippet: Optional[str] = None,
        output_snippet: Optional[str] = None,
        original_length: Optional[int] = None,
        redacted_length: Optional[int] = None,
        redacted_snippets: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Record a safety event to the database (non-blocking).

        This method attempts a best-effort write. If the database is
        unavailable or the write fails, the error is logged but the
        request pipeline continues unaffected.
        """
        if self.db_session is None:
            return

        try:
            # Defer import to avoid circular dependency
            from app.models.ai_safety_event import AISafetyEvent

            event = AISafetyEvent(
                event_type=event_type,
                severity=severity,
                rule_triggered=rule_triggered,
                rule_category=rule_category,
                user_id=user_id,
                session_id=session_id or "",
                organization_id=organization_id,
                trace_id=trace_id,
                input_snippet=input_snippet[:500] if input_snippet else None,
                output_snippet=output_snippet[:500] if output_snippet else None,
                original_length=original_length,
                redacted_length=redacted_length,
                redacted_snippets=redacted_snippets,
                created_at=datetime.utcnow(),
            )

            # Schedule a fire-and-forget write
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._persist_event(event))
            except RuntimeError:
                # No running event loop — skip persistence
                pass

        except Exception:
            logger.debug(
                "Safety event record skipped (non-blocking): %s",
                event_type,
            )

    async def _persist_event(self, event) -> None:
        """Async coroutine to persist a single safety event."""
        try:
            from app.repositories.ai_safety_event_repo import AISafetyEventRepository
            repo = AISafetyEventRepository(self.db_session)
            await repo.create_non_blocking(event)
        except Exception:
            logger.debug(
                "Safety event persistence skipped: %s",
                event.event_type,
            )
