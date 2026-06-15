# US-BKND-AI-048: Dead Letter Queue and Failed AI Job Recovery

**Status:** ✅ COMPLETE
**Priority:** SHOULD
**Sprint:** 7
**Implemented:** 2026-06-15

## Summary

Dead letter queue for capturing, classifying, and recovering failed AI jobs. Automatic failure classification (transient/permanent/provider), exponential backoff retry (2^n * 5s, max 300s), manual recovery/discard, filtering, and monitoring stats.

## Failure Classification

| Category | Examples | Retryable |
|---|---|---|
| TRANSIENT | Timeout, rate limit, 429, 500, 503, network | Yes |
| PERMANENT | Validation error, not found, unauthorized, quota | No |
| PROVIDER | Anthropic/OpenAI API errors | Yes (after cooldown) |
| UNKNOWN | Unclassified errors | Yes (with caution) |

## Job Lifecycle

```
FAILED -> RETRYING -> FAILED (retry loop) -> DEAD (max exhausted)
                                              -> RECOVERED (successful retry)
                                              -> DISCARDED (admin)
```
