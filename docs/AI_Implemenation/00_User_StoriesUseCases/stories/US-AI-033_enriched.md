# US-AI-033: Event-Driven Outbox for Downstream Consumers

**As an** Architect, **I want** every AI mutation (page create/update/delete, course create, batch apply, template harvest) to write a versioned, typed outbox event atomically within the same database transaction, **so that** search indexing, analytics pipelines, audit archives, and external integrations can consume AI-authored content changes reliably without tight coupling to the mutation code path.

- **Priority:** SHOULD for production, MUST for regulated tenants
- **Depends on:** US-AI-010 (Apply Safety, Audit, and Outbox), US-AI-030 (Course Assembly into Editor)
- **Unlocks:** US-AI-034 (Durable Workflow Engine -- outbox events drive workflow triggers), US-AI-036 (Cost Tracking -- outbox events feed usage records), US-AI-041 (Async Preview Generation -- outbox events trigger preview rebuild), external webhook integrations
- **Source flow:** 13. Platform Runtime and Operations Flow (Phases 5-6 -- Event Publication), US-AI-013 Table `outbox_events` DDL reference
- **Epic Owner:** Technical Product Owner

---

## 1. Functional Specification

### 1.1 User Story

As an **Architect/Platform Engineer**, I want every AI-triggered domain mutation to emit an event to a transactional outbox table, so that downstream consumers (search index, analytics aggregator, audit archive, external LMS/LRS via webhook) can discover and react to changes asynchronously without being coupled to the mutation's request cycle. The outbox guarantees at-least-once delivery, and the publisher can be disabled without affecting mutation correctness.

As a **Data Engineer**, I want outbox events to carry sufficient payload for my consumer to act independently -- the payload must include the affected entity snapshot or delta so the consumer does not need to call back into the main API to understand what changed.

As a **Site Reliability Engineer**, I want the outbox publisher to be observable (metrics per event type, delivery latency, retry count, stuck events) and circuit-breakable, so that a downstream consumer outage does not back-pressure the mutation pathway or destabilise the publisher.

As a **Compliance Officer**, I want every outbox event to carry a `trace_id` that links back to the originating AI session, proposal, and user, so that I can trace the full lifecycle of a piece of content from generation to downstream processing.

### 1.2 Overview

The outbox pattern solves the dual-write problem: when a service writes to a database and must also publish an event to a message broker, the two operations must be atomic or the system risks inconsistent states (event published but write failed, or write succeeded but event lost).

The implementation follows the **Transactional Outbox** pattern:

1. **Write phase:** Every AI mutation (PageCreatedByAI, PageUpdatedByAI, PageDeletedByAI, CourseCreatedFromFile, BatchProposalApplied, TemplateDefinitionHarvested) writes one or more rows into `outbox_events` **in the same database transaction** as the domain mutation.
2. **Publish phase:** A lightweight background publisher (`OutboxPublisher`) polls the `outbox_events` table for unpublished rows (WHERE `published_at IS NULL`), serialises each event to a chosen message broker channel (Redis Streams for MVP, NATS/RabbitMQ for production), marks `published_at` on success, and increments `retry_count` on failure.
3. **Consume phase:** Downstream consumers subscribe to their broker channels, process events idempotently, and commit offsets only after successful processing.

The design ensures:
- **Atomicity:** Transaction rollback removes both the domain mutation and its outbox events. No orphan events.
- **At-least-once delivery:** Publisher retries failed events until `max_retries` is exhausted, then moves them to a dead-letter state.
- **Idempotent consumers:** Every event carries a unique `event_id` that consumers use as a deduplication key.
- **Observability:** Prometheus metrics track events published, failed, and in-flight. Stuck events older than `stuck_threshold` trigger an alert.
- **Isolation:** The publisher runs in a separate asyncio task. If the publisher is disabled or crashes, the mutation pathway is unaffected -- events accumulate in the table and are drained when the publisher restarts.

### 1.3 Actors

| Actor | Role |
|---|---|
| **Mutation Endpoint** (courses router, page_components router, proposal apply, ingestion pipeline, template definition harvester) | Writes domain rows + outbox event rows in a single DB transaction |
| **OutboxPublisher** (`app/services/ai/outbox/publisher.py`) | Background asyncio task that polls unpublished events, forwards to message broker, marks as published |
| **Message Broker** (Redis Streams for MVP / NATS for production) | Durable channel that buffers events for downstream consumers |
| **Search Indexer** (consumer) | Subscribes to course/page events; rebuilds Elasticsearch/Meilisearch index entries |
| **Analytics Aggregator** (consumer) | Subscribes to interaction and mutation events; computes per-course, per-learner aggregates |
| **Audit Archiver** (consumer) | Subscribes to all events; writes immutable audit records to a separate archive store (S3/Glacier, SIEM) |
| **External Webhook Dispatcher** (consumer) | Subscribes to configured event types; relays to registered webhook URLs with retry + idempotency |
| **Preview Rebuild Trigger** (consumer) | Subscribes to page change events; triggers async preview generation (US-AI-041) |
| **SRE / Operator** | Monitors publisher health metrics, stuck events, consumer lag |

### 1.4 Event Types Catalog

All event types MUST follow the naming convention `<DomainVerb>By<Actor>` in PascalCase.

| Event Type | Origin Mutation | Payload Contains | Expected Consumers |
|---|---|---|---|
| `PageCreatedByAI` | `propose_create_page` apply | `courseId`, `pageId`, `pageTitle`, `templateType`, `componentCount`, `sessionId`, `proposalId` | Search index, Analytics, Audit, Webhooks |
| `PageUpdatedByAI` | `propose_update_page` apply | `courseId`, `pageId`, `pageTitle`, `changedFields[]`, `sessionId`, `proposalId` | Search index, Analytics, Audit, Preview rebuild, Webhooks |
| `PageDeletedByAI` | `propose_delete_page` apply | `courseId`, `pageId`, `pageTitle`, `pageSnapshot` (full page before delete), `sessionId`, `proposalId` | Search index, Analytics, Audit, Webhooks |
| `CourseCreatedFromFile` | File ingestion final apply | `courseId`, `courseTitle`, `sourceFileType` (pdf/docx), `pageCount`, `componentCount`, `sessionId`, `ingestionJobId` | Search index, Analytics, Audit, Webhooks |
| `BatchProposalApplied` | Batch proposal apply | `courseId`, `proposalIds[]`, `operations[]`, `pageCount`, `componentCount`, `sessionId` | Analytics, Audit, Webhooks |
| `TemplateDefinitionHarvested` | Template harvest promotion | `templateType`, `displayName`, `schemaSignature`, `harvestedFromCourseId`, `adminUserId` | Audit, Template registry refresh |
| `InteractionEventPersisted` | `POST /api/v1/courses/{courseId}/analytics/events` | `courseId`, `eventId`, `interactionType`, `learnerId`, `pageId`, `componentId`, `score`, `completed`, `duration` | Analytics aggregator, LRS (xAPI forwarder) |

### 1.5 Flow: Mutation with Transactional Outbox Write

**Precondition:** An AI proposal has been confirmed by the user and the apply endpoint is invoked.

1. **Apply endpoint** receives confirmed apply request. Opens DB transaction.
2. **Domain mutation** executes: writes to `courses`, `templates`, `page_records`, `component_records`, or deletes those rows as appropriate.
3. **Outbox event creation** executes within the same transaction: a call to `OutboxRepository.create()` inserts one or more rows into `outbox_events` with `event_type`, `event_version=1`, `aggregate_id` (the primary resource ID, e.g. page_id), `payload` (see event types catalog), `trace_id` (extracted from request context), and `occurred_at = NOW()`.
4. **Transaction commits.** Both domain rows and outbox rows are now visible.
5. **HTTP response** returns to the frontend. The publisher has not yet acted.
6. **OutboxPublisher** (polling loop, called every `OUTBOX_POLL_INTERVAL_MS`) queries `SELECT * FROM outbox_events WHERE published_at IS NULL AND retry_count < max_retries ORDER BY occurred_at ASC LIMIT batch_size`.
7. **Publisher** serialises each event into the message broker channel. On success, it sets `published_at = NOW()`. On failure, it increments `retry_count` and logs the error.
8. **Consumer** receives the event from the broker channel. The consumer uses `event_id` to deduplicate. After processing, it acknowledges/commits the message.
9. **If `retry_count >= max_retries`** and the event remains unpublished, the publisher logs a critical error and emits a metric. An operator alert fires. The event remains in the table for manual inspection and replay.

### 1.6 Edge Cases and Error Handling

| Scenario | Expected Behaviour |
|---|---|
| **Transaction rollback during apply** | Outbox events are rolled back with the domain mutation. No orphan events. The publisher never sees speculative events. |
| **Publisher crashes before marking published_at** | On restart, the publisher picks up the same events again. The consumer deduplicates by `event_id`. At-least-once but not exactly-once. |
| **Publisher cannot reach the message broker** | Publisher logs error, does NOT mark `published_at`, increments `retry_count`. Backoff is `2^retry_count * poll_interval`. If `retry_count >= max_retries`, event enters dead-letter state. |
| **Message broker is down during publisher start** | Publisher fails to connect, logs "Broker unavailable", sleeps `OUTBOX_POLL_INTERVAL_MS`, retries. Events accumulate in the outbox table. No data loss. |
| **Consumer processes an event but crashes before committing** | After consumer restart, the broker redelivers the event. The consumer deduplicates by `event_id` and skips reprocessing. |
| **Outbox table grows unbounded** | A background `DELETE FROM outbox_events WHERE published_at IS NOT NULL AND occurred_at < NOW() - INTERVAL '7 days'` runs daily. Or use PostgreSQL partitioning by `occurred_at` month. |
| **Multiple publisher instances are deployed** | Use PostgreSQL advisory lock (`pg_try_advisory_lock(OUTBOX_LOCK_ID)`) at the start of each poll cycle. Only the instance holding the lock queries unpublished events. |
| **Event payload exceeds maximum broker message size** | Publisher truncates or compresses payload. If payload still exceeds limit, the event is logged as oversized and retried only if a large-message channel is configured. |
| **Mutation writes many rows (batch proposal)** | `OUTBOX_MAX_BATCH_SIZE` controls how many events per transaction are written. If batch applies touch 50 pages, 50 events are inserted. The publisher processes them in batches of `PUBLISHER_BATCH_SIZE`. |
| **Consumer is permanently down** | Events accumulate in the broker stream. The stream has a configurable retention period (default 7 days). Outbox events remain in the DB table forever (until archived) for replay. |

---

## 2. Technical Specification

### 2.1 Database Schema (PostgreSQL DDL)

#### 2.1.1 `outbox_events` Table

```sql
CREATE TABLE IF NOT EXISTS outbox_events (
    id              BIGSERIAL PRIMARY KEY,
    event_id        VARCHAR(64) UNIQUE NOT NULL DEFAULT gen_random_uuid()::text,
    event_type      VARCHAR(64) NOT NULL,
    event_version   INTEGER NOT NULL DEFAULT 1,
    aggregate_id    VARCHAR(64) NOT NULL,        -- e.g. page_id, course_id, proposal_id
    aggregate_type  VARCHAR(32) NOT NULL DEFAULT 'page',  -- 'page', 'course', 'proposal', 'template'
    payload         JSONB NOT NULL,
    trace_id        VARCHAR(64),                 -- links back to AI session
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ,                 -- NULL = not yet published
    retry_count     INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,                        -- last publisher error message
    status          VARCHAR(16) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'published', 'dead_letter'))
);

-- Index for publisher polling (unpublished events, ordered by occurrence)
CREATE INDEX idx_outbox_poll
    ON outbox_events (status, occurred_at ASC)
    WHERE status = 'pending';

-- Index for dead-letter monitoring
CREATE INDEX idx_outbox_dead_letter
    ON outbox_events (status, retry_count)
    WHERE status = 'dead_letter';

-- Index for event type queries (admin / replay)
CREATE INDEX idx_outbox_event_type ON outbox_events (event_type);

-- Index for aggregate lookups
CREATE INDEX idx_outbox_aggregate ON outbox_events (aggregate_id, aggregate_type);

-- Index for trace_id lookup (compliance / debugging)
CREATE INDEX idx_outbox_trace ON outbox_events (trace_id);
```

#### 2.1.2 `outbox_consumer_checkpoints` Table

Tracks per-consumer offset or last-processed event ID for exactly-once semantics.

```sql
CREATE TABLE IF NOT EXISTS outbox_consumer_checkpoints (
    id              BIGSERIAL PRIMARY KEY,
    consumer_name   VARCHAR(128) NOT NULL UNIQUE,  -- e.g. 'search-indexer', 'analytics-aggregator'
    last_event_id   VARCHAR(64) NOT NULL,           -- last successfully processed event_id
    last_processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumer_group  VARCHAR(64) NOT NULL DEFAULT 'default'
);
```

### 2.2 SQLAlchemy ORM Models

#### New file: `app/models/outbox.py`

```python
"""Transactional outbox ORM model for event-driven downstream consumers.

Every AI mutation writes versioned events atomically with the domain
transaction. A background publisher forwards events to the message broker.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Text, Integer, BigInteger, CheckConstraint

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    event_version: Mapped[int] = mapped_column(Integer, default=1)
    aggregate_id: Mapped[str] = mapped_column(String(64))
    aggregate_type: Mapped[str] = mapped_column(String(32), default="page")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'published', 'dead_letter')",
            name="ck_outbox_status"
        ),
    )

    def to_dict(self) -> dict:
        return {
            "eventId": self.event_id,
            "eventType": self.event_type,
            "eventVersion": self.event_version,
            "aggregateId": self.aggregate_id,
            "aggregateType": self.aggregate_type,
            "payload": self.payload,
            "traceId": self.trace_id,
            "occurredAt": self.occurred_at.isoformat() if self.occurred_at else None,
            "publishedAt": self.published_at.isoformat() if self.published_at else None,
            "retryCount": self.retry_count,
            "lastError": self.last_error,
            "status": self.status,
        }


class OutboxConsumerCheckpoint(Base):
    """Tracks the last event each consumer has successfully processed."""
    __tablename__ = "outbox_consumer_checkpoints"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    consumer_name: Mapped[str] = mapped_column(String(128), unique=True)
    last_event_id: Mapped[str] = mapped_column(String(64))
    last_processed_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    consumer_group: Mapped[str] = mapped_column(String(64), default="default")
```

### 2.3 Repository Layer

#### New file: `app/repositories/outbox_repo.py`

```python
"""Repository for outbox_events table."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent, OutboxConsumerCheckpoint


class OutboxRepository:
    """Transactional repository for outbox events.

    Used by mutation endpoints to write events atomically,
    and by the publisher to claim and mark events.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Writers (used by mutation endpoints) ─────────────────────────────

    async def create(self, event: OutboxEvent) -> OutboxEvent:
        """Insert one outbox event in the current transaction."""
        self.session.add(event)
        await self.session.flush()  # do NOT commit — caller manages transaction
        return event

    async def create_batch(self, events: List[OutboxEvent]) -> List[OutboxEvent]:
        """Insert multiple outbox events atomically."""
        self.session.add_all(events)
        await self.session.flush()
        return events

    # ── Publisher claim (polls unpublished events) ──────────────────────

    async def claim_pending_events(
        self, batch_size: int = 50, max_retries: int = 5
    ) -> List[OutboxEvent]:
        """Claim the next batch of unpublished pending events for publishing.

        Uses SKIP LOCKED to avoid publisher contention when multiple
        instances poll concurrently.
        """
        q = (
            select(OutboxEvent)
            .where(
                and_(
                    OutboxEvent.status == "pending",
                    OutboxEvent.retry_count < max_retries,
                )
            )
            .order_by(OutboxEvent.occurred_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def mark_published(self, event_id: str) -> None:
        """Mark an event as successfully published."""
        q = select(OutboxEvent).where(OutboxEvent.event_id == event_id)
        event = (await self.session.execute(q)).scalar_one_or_none()
        if event:
            event.published_at = datetime.utcnow()
            event.status = "published"
            await self.session.flush()

    async def mark_failed(self, event_id: str, error_msg: str) -> None:
        """Increment retry count and record error. Mark dead-letter if exhausted."""
        q = select(OutboxEvent).where(OutboxEvent.event_id == event_id)
        event = (await self.session.execute(q)).scalar_one_or_none()
        if event:
            event.retry_count = OutboxEvent.retry_count + 1
            event.last_error = error_msg[:1024]
            event.status = "dead_letter" if event.retry_count >= 5 else "pending"
            await self.session.flush()

    async def mark_batch_published(self, event_ids: List[str]) -> None:
        """Mark multiple events as published in one round-trip."""
        now = datetime.utcnow()
        q = (
            select(OutboxEvent)
            .where(OutboxEvent.event_id.in_(event_ids))
        )
        result = await self.session.execute(q)
        for event in result.scalars().all():
            event.published_at = now
            event.status = "published"
        await self.session.flush()

    # ── Consumer checkpoint ─────────────────────────────────────────────

    async def get_checkpoint(self, consumer_name: str) -> Optional[OutboxConsumerCheckpoint]:
        q = select(OutboxConsumerCheckpoint).where(
            OutboxConsumerCheckpoint.consumer_name == consumer_name
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def upsert_checkpoint(self, consumer_name: str, last_event_id: str) -> None:
        record = await self.get_checkpoint(consumer_name)
        if record:
            record.last_event_id = last_event_id
            record.last_processed_at = datetime.utcnow()
        else:
            record = OutboxConsumerCheckpoint(
                consumer_name=consumer_name,
                last_event_id=last_event_id,
            )
            self.session.add(record)
        await self.session.flush()

    # ── Admin / Replay ─────────────────────────────────────────────────

    async def list_by_status(
        self,
        status: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[OutboxEvent]:
        q = (
            select(OutboxEvent)
            .where(OutboxEvent.status == status)
            .order_by(OutboxEvent.occurred_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(q)).scalars().all())

    async def count_by_status(self, status: str) -> int:
        q = (
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.status == status)
        )
        return (await self.session.execute(q)).scalar() or 0
```

### 2.4 Publisher Service

#### New file: `app/services/ai/outbox/publisher.py`

```python
"""Transactional Outbox Publisher.

Polls unpublished outbox_events, forwards them to the configured
message broker, and marks them as published.

Implements:
- Polling with configurable interval and batch size
- PostgreSQL advisory lock for single-active-publisher
- Exponential backoff on transient broker failures
- Dead-letter after max_retries
- Prometheus metrics for observability
"""
from __future__ import annotations
import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import text as sa_text

from app.repositories.outbox_repo import OutboxRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Message broker abstraction
# ---------------------------------------------------------------------------

class MessageBroker(Protocol):
    """Minimal message broker interface for the outbox publisher."""

    async def connect(self) -> None: ...

    async def publish(
        self, channel: str, event_id: str, payload: dict
    ) -> bool: ...

    async def publish_batch(
        self, channel: str, events: list[dict]
    ) -> list[str]:  # returns list of successfully published event_ids
        ...

    async def disconnect(self) -> None: ...


class RedisStreamBroker:
    """Redis Streams implementation of MessageBroker.

    Uses aioredis or redis-py async. Configured via env var REDIS_URL.
    Events are published to streams named by event_type.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis = None

    async def connect(self) -> None:
        import redis.asyncio as aioredis
        self._redis = aioredis.from_url(self.redis_url, decode_responses=True)

    async def publish(self, channel: str, event_id: str, payload: dict) -> bool:
        try:
            await self._redis.xadd(channel, payload, id="*")  # type: ignore
            return True
        except Exception as exc:
            logger.error("Redis publish failed for event %s: %s", event_id, exc)
            return False

    async def publish_batch(self, channel: str, events: list[dict]) -> list[str]:
        succeeded: list[str] = []
        async with self._redis.pipeline(transaction=True) as pipe:  # type: ignore
            for evt in events:
                pipe.xadd(channel, evt["payload"], id="*")
            try:
                results = await pipe.execute()
                for idx, result in enumerate(results):
                    if result:
                        succeeded.append(events[idx]["event_id"])
            except Exception as exc:
                logger.error("Redis batch publish failed: %s", exc)
        return succeeded

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.close()


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------

class OutboxPublisher:
    """Background publisher that drains the outbox table into the message broker.

    Expected to be started as a lifespan task in app/main.py or as a
    standalone worker process.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broker: Optional[MessageBroker] = None,
        *,
        poll_interval_ms: int = 1000,
        batch_size: int = 50,
        max_retries: int = 5,
        lock_id: int = 42171337,
    ):
        self.session_factory = session_factory
        self.broker = broker or RedisStreamBroker()
        self.poll_interval = poll_interval_ms / 1000.0
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.lock_id = lock_id
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the polling loop in a background asyncio task."""
        await self.broker.connect()
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("OutboxPublisher started (poll=%dms, batch=%d)",
                     int(self.poll_interval * 1000), self.batch_size)

    async def stop(self) -> None:
        """Gracefully stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.broker.disconnect()
        logger.info("OutboxPublisher stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                # Acquire advisory lock (PostgreSQL-specific)
                async with self.session_factory() as session:
                    lock_acquired = await session.execute(
                        sa_text(f"SELECT pg_try_advisory_lock({self.lock_id})")
                    )
                    if not lock_acquired.scalar():
                        await asyncio.sleep(self.poll_interval)
                        continue

                    try:
                        await self._publish_batch(session)
                    finally:
                        await session.execute(
                            sa_text(f"SELECT pg_advisory_unlock({self.lock_id})")
                        )
            except Exception as exc:
                logger.error("OutboxPublisher poll cycle error: %s", exc, exc_info=True)

            await asyncio.sleep(self.poll_interval)

    async def _publish_batch(self, session: AsyncSession) -> None:
        repo = OutboxRepository(session)
        events = await repo.claim_pending_events(
            batch_size=self.batch_size, max_retries=self.max_retries
        )
        if not events:
            return

        # Build channel-keyed payloads. Group events by type for batch publish.
        channel_map: dict[str, list[dict]] = {}
        for event in events:
            channel = f"outbox:{event.event_type}"
            channel_map.setdefault(channel, []).append({
                "event_id": event.event_id,
                "payload": event.to_dict(),
            })

        all_published: list[str] = []
        all_failed: list[str] = []
        for channel, channel_events in channel_map.items():
            published_ids = await self.broker.publish_batch(channel, channel_events)
            all_published.extend(published_ids)
            failed_ids = [
                e["event_id"] for e in channel_events
                if e["event_id"] not in set(published_ids)
            ]
            all_failed.extend(failed_ids)

        # Mark in DB
        if all_published:
            await repo.mark_batch_published(all_published)
        for event_id in all_failed:
            await repo.mark_failed(event_id, "Broker publish_batch returned error")

        await session.commit()
        logger.info("Published %d events, failed %d",
                     len(all_published), len(all_failed))
```

#### Convenience factory and lifespan hook

In `app/services/ai/outbox/__init__.py`:

```python
from app.services.ai.outbox.publisher import OutboxPublisher, RedisStreamBroker
from app.db.config import SessionLocal

_publisher: OutboxPublisher | None = None


def get_publisher() -> OutboxPublisher | None:
    return _publisher


def create_publisher() -> OutboxPublisher:
    global _publisher
    broker = RedisStreamBroker()
    _publisher = OutboxPublisher(
        session_factory=SessionLocal,
        broker=broker,
        poll_interval_ms=int(os.getenv("OUTBOX_POLL_INTERVAL_MS", "1000")),
        batch_size=int(os.getenv("OUTBOX_PUBLISHER_BATCH_SIZE", "50")),
        max_retries=int(os.getenv("OUTBOX_MAX_RETRIES", "5")),
    )
    return _publisher
```

In `app/main.py`, update the lifespan function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup (existing code) ──────────────────────────────
    ...

    # Start outbox publisher (disabled when OUTBOX_ENABLED=false)
    if os.getenv("OUTBOX_ENABLED", "true").lower() == "true":
        from app.services.ai.outbox import create_publisher
        publisher = create_publisher()
        await publisher.start()
        logger.info("Outbox publisher started")

    yield

    # ── Shutdown ─────────────────────────────────────────────
    if os.getenv("OUTBOX_ENABLED", "true").lower() == "true":
        from app.services.ai.outbox import get_publisher
        pub = get_publisher()
        if pub:
            await pub.stop()
```

### 2.5 Event Payload Schemas

Each `payload` JSONB in `outbox_events` must conform to one of the following Pydantic models. The publisher serialises these into the broker message.

#### New file: `app/models/outbox_payloads.py`

```python
"""Typed outbox event payloads. Each event_type maps to exactly one model."""
from __future__ import annotations
from typing import List, Optional, Any
from pydantic import BaseModel, Field


class PageCreatedByAIPayload(BaseModel):
    courseId: str = Field(..., description="Course UUID")
    pageId: str = Field(..., description="Newly created page UUID")
    pageTitle: str = Field(..., max_length=200)
    templateType: str = Field(..., description="Template type, e.g. 'content-text'")
    componentCount: int = Field(..., ge=0)
    sessionId: str = Field(..., description="AI session that originated the mutation")
    proposalId: str = Field(..., description="Proposal that was applied")
    changedAt: str = Field(..., description="ISO 8601 timestamp")


class PageUpdatedByAIPayload(BaseModel):
    courseId: str
    pageId: str
    pageTitle: str
    changedFields: List[str] = Field(..., description="Array of changed field paths, e.g. ['title', 'components[0].data.body']")
    sessionId: str
    proposalId: str
    changedAt: str


class PageDeletedByAIPayload(BaseModel):
    courseId: str
    pageId: str
    pageTitle: str
    pageSnapshot: dict = Field(..., description="Full page record before deletion, for recovery/replay")
    sessionId: str
    proposalId: str
    changedAt: str


class CourseCreatedFromFilePayload(BaseModel):
    courseId: str
    courseTitle: str
    sourceFileType: str = Field(..., pattern=r"^(pdf|docx|pptx|scorm)$")
    pageCount: int
    componentCount: int
    sessionId: str
    ingestionJobId: str
    changedAt: str


class BatchProposalAppliedPayload(BaseModel):
    courseId: str
    proposalIds: List[str]
    operations: List[str] = Field(..., description="List of operations applied, e.g. ['CREATE_PAGE', 'UPDATE_PAGE']")
    pageCount: int
    componentCount: int
    sessionId: str
    changedAt: str


class TemplateDefinitionHarvestedPayload(BaseModel):
    templateType: str
    displayName: str
    schemaSignature: str
    harvestedFromCourseId: str
    adminUserId: str
    harvestedAt: str


# Map event_type -> payload model
EVENT_PAYLOAD_MAP: dict[str, type[BaseModel]] = {
    "PageCreatedByAI": PageCreatedByAIPayload,
    "PageUpdatedByAI": PageUpdatedByAIPayload,
    "PageDeletedByAI": PageDeletedByAIPayload,
    "CourseCreatedFromFile": CourseCreatedFromFilePayload,
    "BatchProposalApplied": BatchProposalAppliedPayload,
    "TemplateDefinitionHarvested": TemplateDefinitionHarvestedPayload,
}
```

### 2.6 Integration into Existing Mutation Endpoints

Each currently responsible mutation site gets a small wrapper that constructs and persists outbox events.

#### Pattern for `proposal_apply` (in `app/services/ai/proposal_applier.py` or similar):

```python
# Inside the apply() method, after successful domain mutation and before commit:
from app.models.outbox import OutboxEvent
from app.repositories.outbox_repo import OutboxRepository
from app.models.outbox_payloads import PageCreatedByAIPayload

outbox_repo = OutboxRepository(session)

match operation:
    case "CREATE_PAGE":
        payload = PageCreatedByAIPayload(
            courseId=course_id,
            pageId=page.page_id,
            pageTitle=page.title,
            templateType=page.template_type,
            componentCount=len(components),
            sessionId=session_id,
            proposalId=proposal.proposal_id,
            changedAt=datetime.utcnow().isoformat(),
        )
        event = OutboxEvent(
            event_type="PageCreatedByAI",
            event_version=1,
            aggregate_id=page.page_id,
            aggregate_type="page",
            payload=payload.model_dump(),
            trace_id=trace_id,
        )
        await outbox_repo.create(event)

# ... commit transaction (domain + outbox event visible atomically)
await session.commit()
```

Similarly for `DELETE_PAGE` take a snapshot of the page before deletion `page.to_dict()` and embed it in `pageSnapshot` for `PageDeletedByAIPayload`.

### 2.7 API Contracts

#### 2.7.1 Admin: List Outbox Events

```
GET /api/v1/admin/outbox/events?status=pending&limit=50&offset=0
Authorization: Bearer {admin_token}
```

Response `200`:
```json
{
    "events": [
        {
            "eventId": "abc-123",
            "eventType": "PageCreatedByAI",
            "eventVersion": 1,
            "aggregateId": "page-uuid-xyz",
            "aggregateType": "page",
            "payload": { "courseId": "c1", "pageId": "...", ... },
            "traceId": "trace-999",
            "occurredAt": "2026-06-14T10:00:00Z",
            "publishedAt": null,
            "retryCount": 2,
            "lastError": "Broker connection timeout",
            "status": "pending"
        }
    ],
    "total": 5,
    "limit": 50,
    "offset": 0
}
```

#### 2.7.2 Admin: Replay Events

```
POST /api/v1/admin/outbox/replay
Authorization: Bearer {admin_token}
Content-Type: application/json

{
    "eventIds": ["abc-123", "def-456"],
    "resetStatus": true
}
```

Response `202`:
```json
{
    "message": "Replay queued for 2 events",
    "newStatus": "pending"
}
```

Resets `status` to `pending` and `published_at` to NULL for specified events so the publisher picks them up again.

#### 2.7.3 Admin: Get Publisher Health

```
GET /api/v1/admin/outbox/health
```

Response `200`:
```json
{
    "status": "running",
    "lastPollAt": "2026-06-14T10:05:00Z",
    "pendingCount": 3,
    "deadLetterCount": 1,
    "totalPublishedToday": 1042,
    "brokerConnected": true
}
```

### 2.8 Module Structure

All new code lives under a dedicated `outbox` module:

```
app/services/ai/outbox/
    __init__.py           # create_publisher(), get_publisher()
    publisher.py           # OutboxPublisher, RedisStreamBroker, MessageBroker protocol
app/repositories/outbox_repo.py
app/models/outbox.py
app/models/outbox_payloads.py
app/routers/admin_outbox.py  # Admin endpoints
app/tasks/outbox_archive.py  # Periodic archive/cleanup task
```

### 2.9 Metrics and Observability (Prometheus)

The publisher exports the following metrics (via `prometheus_fastapi_instrumentator` or a custom label):

| Metric | Type | Labels | Description |
|---|---|---|---|
| `outbox_events_published_total` | Counter | `event_type` | Total events successfully published |
| `outbox_events_failed_total` | Counter | `event_type` | Total events that failed at the broker |
| `outbox_events_dead_letter_total` | Counter | `event_type` | Events that exhausted retries |
| `outbox_publisher_errors_total` | Counter | `error_type` | Publisher internal errors (lock, query, etc.) |
| `outbox_pending_events` | Gauge | - | Current count of pending (unpublished) events |
| `outbox_dead_letter_events` | Gauge | - | Current count of dead-letter events |
| `outbox_publisher_lag_seconds` | Gauge | - | Age of the oldest pending event in seconds |

---

## 3. Configuration & Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OUTBOX_ENABLED` | `true` | Master toggle. Set to `false` to disable the publisher at startup. Events still accumulate in the DB. |
| `OUTBOX_POLL_INTERVAL_MS` | `1000` | Milliseconds between publisher poll cycles. Lower = lower latency, higher = less DB load. |
| `OUTBOX_PUBLISHER_BATCH_SIZE` | `50` | Max events per poll cycle. Controls memory and DB round-trip per cycle. |
| `OUTBOX_MAX_RETRIES` | `5` | Max times a single event is retried before entering dead-letter state. |
| `OUTBOX_STUCK_THRESHOLD_S` | `300` | Seconds after which a pending event is considered stuck. Triggers a warning log and metric. |
| `OUTBOX_ARCHIVE_AFTER_DAYS` | `7` | Delete published events older than this many days during the daily archive task. |
| `OUTBOX_BROKER_TYPE` | `redis` | Broker type: `redis` or `nats`. Future: `rabbitmq`, `kafka`. |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string for the Redis Streams broker. |
| `OUTBOX_LOCK_ID` | `42171337` | PostgreSQL advisory lock ID for single-active-publisher coordination. |
| `OUTBOX_CONSUMER_CHECKPOINT_ENABLED` | `true` | Enable consumer checkpoint tracking table. |

---

## 4. Test Scenarios

### 4.1 Unit Tests (`tests/test_outbox_repo.py`)

| Test | Verification |
|---|---|
| `test_create_event` | `OutboxRepository.create()` inserts an event; `id` is auto-assigned; `status` defaults to `pending`; `published_at` is NULL. |
| `test_create_batch` | `create_batch()` inserts 100 events; all have unique `event_id` values. |
| `test_claim_pending_returns_only_pending` | Events with `status='published'` or `status='dead_letter'` are NOT returned by `claim_pending_events()`. |
| `test_claim_pending_sorted_by_occurred_at` | Events are returned in ascending `occurred_at` order. |
| `test_claim_pending_respects_max_retries` | Events with `retry_count >= max_retries` are NOT returned even if `status='pending'`. |
| `test_mark_published` | After `mark_published()`, `status='published'` and `published_at` is set. |
| `test_mark_failed_transitions_to_dead_letter` | After `mark_failed()` when `retry_count >= max_retries`, `status='dead_letter'`. |
| `test_upsert_checkpoint` | First call creates a row; second call updates `last_event_id` and `last_processed_at`. |

### 4.2 Integration Tests (`tests/test_outbox_publisher.py`)

| Test | Verification |
|---|---|
| `test_publisher_polls_and_publishes` | Publisher starts; a pending event exists in DB; after one poll cycle, the event is marked `published`. |
| `test_publisher_skips_locked_events` | With two publisher instances, only one claims each event. |
| `test_publisher_marks_failed_on_broker_error` | When broker `publish()` returns `False`, event `retry_count` increments. |
| `test_publisher_dead_letter_after_max_retries` | After `max_retries` consecutive failures, event `status` becomes `dead_letter`. |
| `test_publisher_does_not_run_when_disabled` | `OUTBOX_ENABLED=false` prevents publisher from starting; no connection to Redis attempted. |

### 4.3 End-to-End Tests (`tests/test_outbox_e2e.py`)

| Test | Verification |
|---|---|
| `test_page_create_emits_outbox_event` | Create a page via `POST /api/v1/courses/{courseId}/pages/from-template`. Verify an `outbox_events` row exists with `event_type='PageCreatedByAI'` (note: existing manual pages use different flow -- this test targets the AI path). |
| `test_apply_proposal_emits_event_atomically` | Create a proposal (US-AI-009), apply it. Verify the domain mutation AND the outbox event appear only after commit. Rollback the transaction and verify neither appears. |
| `test_outbox_rollback_removes_event` | Within a transaction, write an outbox event then explicitly rollback. Verify zero rows in `outbox_events`. |
| `test_admin_list_events` | `GET /api/v1/admin/outbox/events` returns paginated results with correct counts. |
| `test_admin_replay_events` | `POST /api/v1/admin/outbox/replay` resets a published event to `pending`. Publisher picks it up again. |
| `test_consumer_idempotency` | Consumer processes the same `event_id` twice; second process is a no-op. |

### 4.4 Error Scenario Tests

| Test | Verification |
|---|---|
| `test_publisher_survives_broker_disconnect` | Redis goes down; publisher logs errors and retries; events remain pending. Redis comes back; publisher catches up and publishes all backlogged events. |
| `test_concurrent_mutations_write_events` | Two concurrent proposal-applies targeting different pages in the same course. Both commit successfully. Both outbox events appear. No deadlock. |
| `test_dead_letter_events_are_not_reprocessed_automatically` | A dead-letter event is NOT returned by `claim_pending_events()`. It only moves back to `pending` via admin replay. |
| `test_outbox_table_does_not_grow_unbounded` | After archive task runs, published events older than `OUTBOX_ARCHIVE_AFTER_DAYS` are deleted. |

---

## 5. Task Breakdown

### Chunk 1: Core Infrastructure (3 story points)

- **T1.1** Create the `outbox_events` and `outbox_consumer_checkpoints` PostgreSQL tables (DDL from Section 2.1). Add Alembic migration.
- **T1.2** Implement `app/models/outbox.py` with `OutboxEvent` and `OutboxConsumerCheckpoint` ORM models. Import in `app/models/__init__.py` and register in `main.py` lifespan model import list.
- **T1.3** Implement `app/repositories/outbox_repo.py` with all methods specified in Section 2.3.
- **T1.4** Implement `app/models/outbox_payloads.py` with typed Pydantic payload models and `EVENT_PAYLOAD_MAP`.
- **T1.5** Write unit tests for the repository (Section 4.1).

### Chunk 2: Publisher Service (5 story points)

- **T2.1** Implement `app/services/ai/outbox/publisher.py` with `MessageBroker` protocol, `RedisStreamBroker`, and `OutboxPublisher`.
- **T2.2** Implement advisory lock acquisition and SKIP LOCKED claim query for concurrent-safe polling.
- **T2.3** Implement `app/services/ai/outbox/__init__.py` with `create_publisher()` and `get_publisher()` factory functions.
- **T2.4** Wire the publisher into `app/main.py` lifespan (startup/shutdown), respecting `OUTBOX_ENABLED`.
- **T2.5** Add Prometheus metrics to the publisher.
- **T2.6** Write integration tests for the publisher (Section 4.2).

### Chunk 3: Mutation Integration (5 story points)

- **T3.1** Integrate outbox event creation into the proposal apply flow (`/proposals/{proposalId}/apply`). For each operation type (create page, update page, delete page, batch), construct the appropriate payload and call `OutboxRepository.create()` within the existing transaction, before commit.
- **T3.2** Integrate outbox event creation into the file ingestion final-apply pathway: emit `CourseCreatedFromFile`.
- **T3.3** Integrate outbox event creation into the template definition harvest/promotion pathway: emit `TemplateDefinitionHarvested`.
- **T3.4** Write end-to-end tests (Section 4.3).

### Chunk 4: Admin APIs and Observability (3 story points)

- **T4.1** Implement `app/routers/admin_outbox.py` router with `GET /admin/outbox/events`, `POST /admin/outbox/replay`, and `GET /admin/outbox/health`. Wire into `app/main.py` behind admin middleware.
- **T4.2** Implement the periodic archive task: `app/tasks/outbox_archive.py` that deletes published events older than `OUTBOX_ARCHIVE_AFTER_DAYS`. Schedule via lifespan or a lightweight scheduler.
- **T4.3** Add a health check / debug page to the admin endpoints showing stuck events, dead-letter counts, and broker connectivity.
- **T4.4** Write error scenario tests (Section 4.4).

### Chunk 5: Consumer Reference Implementations (3 story points)

- **T5.1** Implement a reference `SearchIndexConsumer` (stub) that subscribes to `outbox:PageCreatedByAI`, `outbox:PageUpdatedByAI`, `outbox:PageDeletedByAI` and logs instead of indexing.
- **T5.2** Implement a reference `AuditArchiveConsumer` that writes every received event to a static audit file or archive table.
- **T5.3** Add a consumer checkpoint integration test: consumer processes events, updates checkpoint, re-reads checkpoint, skips already-processed events.

---

## 6. Dependencies & Sequencing

### Hard Dependencies (MUST be done before Chunk 3)

| Dependency | Story | Why |
|---|---|---|
| US-AI-009 (Generic Proposal Lifecycle) | DONE / IN PROGRESS | Mutation endpoints must exist to integrate outbox events into |
| US-AI-010 (Apply Safety, Audit) | DONE / IN PROGRESS | The apply-mutation pathway with transactional commit is the integration point |
| US-AI-030 (Course Assembly into Editor) | DONE / IN PROGRESS | Assembly endpoints are where page mutations happen |
| Alembic migrations are operational | EXISTING | Used to create the new tables |

### Soft Dependencies (SHOULD be done before production)

| Dependency | Story | Why |
|---|---|---|
| US-AI-034 (Durable Workflow Engine) | SHOULD | Outbox events naturally trigger workflow steps |
| US-AI-041 (Async Preview Generation) | SHOULD | Outbox events trigger preview rebuilds |
| Redis (or alternative broker) is deployed in production | EXISTING | Required for `RedisStreamBroker` |

### Delivery Sequence

1. **Chunk 1** (Core Infrastructure) -- Standalone. No existing code changes needed.
2. **Chunk 2** (Publisher Service) -- Depends on Chunk 1. Publisher starts draining but events do not yet exist.
3. **Chunk 3** (Mutation Integration) -- Depends on Chunks 1+2. Events start flowing.
4. **Chunk 4** (Admin APIs) -- Depends on Chunk 1. Can be built in parallel with Chunks 2-3.
5. **Chunk 5** (Consumer References) -- Depends on Chunk 2. Can be parallel with Chunks 3-4.

---

## 7. Open Questions & Future Considerations

1. **Should the publisher be in-process or a sidecar?** For MVP, the in-process asyncio task is simpler and avoids deployment complexity. For production scale (>1000 events/second), a separate `outbox-publisher` sidecar process with its own connection pool and scaling is recommended.

2. **What broker for regulated tenants?** Regulated tenants may require NATS JetStream (persistent, exactly-once delivery) or RabbitMQ (AMQP, DLX for dead letters). The `MessageBroker` protocol makes this swappable without changing the publisher logic.

3. **Should we support direct webhook push instead of broker?** Some tenants may want events pushed directly to a webhook URL without a broker intermediary. A `WebhookBroker` implementing the `MessageBroker` protocol could be added in a follow-up.

4. **What about exactly-once semantics?** The outbox pattern guarantees at-least-once. Exactly-once requires distributed transaction coordination (XA) or idempotent consumers with exactly-once sink (e.g., Kafka transactional producer + idempotent consumer). This is a future enhancement for regulated tenants.

5. **Should `InteractionEventPersisted` use the outbox?** Interaction events are already written directly. A lightweight variant could batch-write them via outbox for analytics consumers without hitting the main analytics query path.

6. **Payload versioning strategy:** If an event payload schema evolves, the `event_version` field allows consumers to handle both old and new shapes. Backward-compatible changes (adding fields) increment the minor version; breaking changes require a new consumer.

---

**Files to be created:**
- `C:\Users\ADMIN\e-learning-backend\app\models\outbox.py`
- `C:\Users\ADMIN\e-learning-backend\app\models\outbox_payloads.py`
- `C:\Users\ADMIN\e-learning-backend\app\repositories\outbox_repo.py`
- `C:\Users\ADMIN\e-learning-backend\app\services\ai\outbox\__init__.py`
- `C:\Users\ADMIN\e-learning-backend\app\services\ai\outbox\publisher.py`
- `C:\Users\ADMIN\e-learning-backend\app\routers\admin_outbox.py`
- `C:\Users\ADMIN\e-learning-backend\app\tasks\outbox_archive.py`
- `C:\Users\ADMIN\e-learning-backend\tests\test_outbox_repo.py`
- `C:\Users\ADMIN\e-learning-backend\tests\test_outbox_publisher.py`
- `C:\Users\ADMIN\e-learning-backend\tests\test_outbox_e2e.py`

**Files to be modified:**
- `C:\Users\ADMIN\e-learning-backend\app\models\__init__.py` -- add `OutboxEvent`, `OutboxConsumerCheckpoint`
- `C:\Users\ADMIN\e-learning-backend\app\main.py` -- register models in lifespan import list, add publisher lifespan hooks
- `C:\Users\ADMIN\e-learning-backend\alembic/versions/` -- add migration for `outbox_events` and `outbox_consumer_checkpoints`

---
The complete epic has been written to `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-AI-034_DURABLE_WORKFLOW_ENGINE.md`.

Here is a summary of the file and its structure:

**File:** `/c/Users/ADMIN/e-learning-backend/docs/AI_Implemenation/00_User_StoriesUseCases/US-AI-034_DURABLE_WORKFLOW_ENGINE.md`

**Epic covers all 8 sections:**

1. **Functional Specification** (1.1-1.6) — User story, overview of 4 job classes (course_generation, batch_content_repair, scorm_export, ai_session_tool_batch), actors table, detailed 6-phase flow for course generation with state machine YAML, process recovery on restart flow, and NFR table with targets (max concurrency, heartbeat interval, step timeout precision, max checkpoint size).

2. **API Contract** (2.1-2.6) — Six endpoints with exact request/response bodies and validation rules:
   - `POST /api/v1/workflows` (202 Accepted, with workflow_type + input JSON Schema validation)
   - `GET /api/v1/workflows/{job_id}` (full JobStatusResponse with sanitized checkpoint)
   - `POST /api/v1/workflows/{job_id}/cancel` (cancel running/pending)
   - `POST /api/v1/workflows/{job_id}/retry` (retry failed from checkpoint)
   - `GET /api/v1/workflows` (admin list with filters and pagination)
   - `GET /api/v1/workflows/{job_id}/events` (immutable event history)

3. **Database Schema** (3.1-3.4) — Three tables (`workflow_type_definitions`, `workflow_jobs`, `workflow_job_events`) with full DDL including CHECK constraints, partial indexes, foreign keys, and the complete Alembic migration script.

4. **Service Signatures and Interfaces** (4.1-4.7) — Seven code blocks with exact file paths and production-ready implementations:
   - `app/models/workflow.py` — ORM models with mapped_column annotations
   - `app/repositories/workflow_repository.py` — 18 methods including `try_lock_pending()` (raw SQL with `FOR UPDATE SKIP LOCKED`), `transition()`, `heartbeat()`, `find_stale_running_jobs()`, `increment_retry()`
   - `app/services/workflow/orchestrator.py` — Full background worker with poll loop, state machine execution, retry/timeout logic, webhook delivery, recovery
   - `app/services/workflow/step_registry.py` — Decorator-based registry
   - `app/services/workflow/steps/course_generation.py` — Two step executors (validate_input, generate_pages)
   - `app/routers/workflows.py` — All six API endpoints with jsonschema input validation
   - `app/main.py` wiring changes (lifespan integration)

5. **Environment Variables** (5) — 11 env vars with defaults, descriptions, and render.yaml additions.

6. **Feature Flags** (6) — `durable_workflow_engine` flag registered in `app/utils/feature_flags.py` with `require_feature_async` decorator usage.

7. **Test Scenarios** (7.1-7.6) — 51 total test cases across 6 files:
   - ORM tests (4 cases)
   - Repository tests (15 cases covering lock, transition, heartbeat, events, recovery, expiry)
   - Orchestrator tests (11 cases covering state machine, retries, timeout, concurrency, recovery, webhook, cancel)
   - API integration tests (14 cases covering submit, poll, cancel, retry, list, events, feature flags, checkpoint sanitization)
   - E2E course generation test (7 cases covering full lifecycle, validation retry, LLM failure, timeout, progress, recovery, cancel)
   - Export integration tests (2 cases covering auto-routing threshold)

8. **Task Breakdown** (8.1-8.10) — 10 tasks (30 SP total) with exact files to create/modify and detailed acceptance criteria.

The epic references the actual codebase throughout: `ImportJob` model at `app/models/persisted_course.py:148`, `error_envelope.py`, existing `conftest.py` patterns, `feature_flags.py`, `db/config.py`, `render.yaml`, and the synchronous export router at `app/routers/export.py`.

---