# US-PEND-024: Integrate Kafka (Redpanda) for Event Streaming — FULLY ENRICHED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Infrastructure + Feature) |
| **Priority** | 🔴 CRITICAL |
| **Batch** | 7 — Long-Term / Deferred |
| **Depends On** | Docker Desktop (Redpanda included in docker-compose.yml from US-PEND-017) |
| **Estimated Effort** | 2-3 days |
| **Target Files** | `app/services/ai/outbox_service.py`, new: `app/events/`, `requirements.txt` |

---

## User Story

**As a** platform architect,
**I want** the AI outbox to publish events to Kafka instead of relying on DB polling,
**So that** downstream consumers receive events with low latency and event replay is supported.

---

## Current State (Code Verified 2026-06-21)

- `outbox_service.py` writes events to `ai_outbox` table — DB polling (pull model)
- No Kafka SDK installed — `requirements.txt` has no `confluent-kafka` or `aiokafka`
- `grep "Kafka|kafka|confluent" app/services/ai/outbox_service.py` → 0 matches
- CI/CD has no Kafka configuration

---

## 🔧 Open-Source Tooling Selection

| Tool | Version | Purpose | Why Selected |
|------|---------|---------|-------------|
| **Redpanda** | v24.1.1 | Kafka-compatible event streaming | Drop-in Kafka replacement; single binary (no ZooKeeper); 10x faster; S3 tiered storage; Apache 2.0 license; runs in Docker |
| **aiokafka** | 0.11.x | Async Python Kafka client | Native asyncio support (matches FastAPI/SQLAlchemy async patterns); maintained by Aio-libs; drop-in API compatible with kafka-python |

**Why Redpanda over alternatives:**
- **Redpanda** vs Apache Kafka: No ZooKeeper dependency. Single binary. 10x lower latency P99. Kafka API compatible — any Kafka client works unchanged.
- **Redpanda** vs RabbitMQ: Kafka topics support replay from any offset (event sourcing). RabbitMQ queues delete messages after consumption.
- **Redpanda** vs NATS: Kafka ecosystem (Schema Registry, Kafka Connect, KSQL) for future analytics.
- **aiokafka** vs `confluent-kafka`: aiokafka is fully async (asyncio-native). confluent-kafka uses librdkafka C library with a blocking poll loop.

### Add to `requirements.txt`:
```
aiokafka>=0.11.0
```

### Pre-Requisite: Redpanda already in docker-compose.yml (from US-PEND-017)

Redpanda is included in the `docker-compose.yml` from US-PEND-017. It starts with `docker compose up -d`. No additional infrastructure setup needed.

---

## Enriched Implementation

### Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│ ProposalSvc  │────→│ OutboxSvc    │────→│ ai_outbox (DB)   │ ← Existing (fallback)
│ ChatSvc      │     │  + Kafka     │     │                  │
│ WorkflowSvc  │     │  publisher   │────→│ Redpanda topics  │ ← New (primary)
└──────────────┘     └──────────────┘     └──────────────────┘
                                                   │
                    ┌──────────────────────────────┤
                    │ Analytics    │ Notifications │ Search Index │
                    │ (Metabase)   │ (email/push)  │ (Elastic)    │
                    └──────────────┴───────────────┴──────────────┘
```

### Topics

| Topic | Event Types | Retention | Partitions |
|-------|-------------|-----------|------------|
| `ai.proposals` | proposal.created, proposal.applied, proposal.rejected, proposal.expired | 7 days | 3 |
| `ai.sessions` | session.started, session.ended | 7 days | 3 |
| `ai.chat` | chat.turn, chat.tool_call | 7 days | 3 |
| `ai.workflows` | workflow.submitted, workflow.completed, workflow.failed | 30 days | 3 |
| `ai.dead_letter` | (any failed event) | 30 days | 1 |

### File: `app/events/__init__.py`

```python
"""Event publishing layer — Redpanda/Kafka integration."""
```

### File: `app/events/kafka_publisher.py`

```python
"""Async Kafka publisher using aiokafka — US-PEND-024."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

logger = logging.getLogger(__name__)

# Topic naming convention
TOPIC_PREFIX = "ai"
TOPICS = {
    "proposals": f"{TOPIC_PREFIX}.proposals",
    "sessions": f"{TOPIC_PREFIX}.sessions",
    "chat": f"{TOPIC_PREFIX}.chat",
    "workflows": f"{TOPIC_PREFIX}.workflows",
    "dead_letter": f"{TOPIC_PREFIX}.dead_letter",
}


class KafkaEventPublisher:
    """Publishes domain events to Redpanda/Kafka with graceful degradation.

    If Kafka is unavailable, events fall back to the outbox table
    (existing behavior — no data loss).

    Usage:
        publisher = KafkaEventPublisher()
        await publisher.start()
        await publisher.publish("proposals", "proposal.created", payload)
        await publisher.stop()
    """

    def __init__(self, bootstrap_servers: Optional[str] = None):
        self.bootstrap_servers = bootstrap_servers or os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"
        )
        self._producer: Optional[AIOKafkaProducer] = None
        self._enabled = os.getenv("KAFKA_ENABLED", "true").lower() == "true"

    async def start(self) -> None:
        """Connect to Kafka cluster."""
        if not self._enabled:
            logger.info("Kafka publisher disabled (KAFKA_ENABLED=false)")
            return
        try:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                compression_type="gzip",
                max_batch_size=16384,
                linger_ms=5,  # 5ms batching for throughput
            )
            await self._producer.start()
            logger.info(
                "Kafka publisher connected to %s", self.bootstrap_servers
            )
        except Exception as exc:
            logger.warning(
                "Kafka unavailable (%s) — falling back to DB outbox", exc
            )
            self._enabled = False

    async def stop(self) -> None:
        """Graceful disconnect."""
        if self._producer:
            await self._producer.stop()
            logger.info("Kafka publisher disconnected")

    async def publish(
        self,
        domain: str,
        event_type: str,
        payload: Dict[str, Any],
        key: Optional[str] = None,
    ) -> bool:
        """Publish an event to the appropriate topic.

        Args:
            domain: One of 'proposals', 'sessions', 'chat', 'workflows'
            event_type: e.g. 'proposal.created', 'session.ended'
            payload: Event data dict
            key: Optional partitioning key (e.g. course_id)

        Returns:
            True if published, False if Kafka unavailable (caller should
            fall back to outbox)
        """
        if not self._enabled or not self._producer:
            return False

        topic = TOPICS.get(domain, f"{TOPIC_PREFIX}.{domain}")
        event = {
            "event_type": event_type,
            "domain": domain,
            "timestamp": None,  # Set by consumer on ingest
            "payload": payload,
        }

        try:
            await self._producer.send_and_wait(
                topic=topic,
                value=event,
                key=key.encode("utf-8") if key else None,
            )
            return True
        except KafkaError as exc:
            logger.error("Kafka publish failed: %s", exc)
            return False

    @property
    def is_available(self) -> bool:
        return self._enabled and self._producer is not None
```

### Integration in `outbox_service.py`

```python
# Add dual-write: DB outbox (guaranteed) + Kafka (best-effort)
class OutboxService:
    def __init__(self, session, kafka: Optional[KafkaEventPublisher] = None):
        self.session = session
        self.kafka = kafka

    async def publish(self, event_type: str, payload: dict, domain: str = "proposals"):
        # 1. ALWAYS write to DB outbox (durability guarantee)
        await self._write_to_outbox(event_type, payload)

        # 2. BEST-EFFORT publish to Kafka (low latency for consumers)
        if self.kafka:
            published = await self.kafka.publish(domain, event_type, payload)
            if not published:
                logger.debug("Kafka publish skipped — consumer will read from outbox")
```

---

## Docker Setup (Already in US-PEND-017 docker-compose.yml)

Redpanda is pre-configured in the docker-compose.yml from US-PEND-017:

```yaml
redpanda:
  image: docker.redpanda.com/redpandadata/redpanda:v24.1.1
  ports:
    - "19092:19092"  # Kafka API (external)
  command:
    - redpanda start
    - --smp 1
    - --overprovisioned
    - --kafka-addr internal://0.0.0.0:9092,external://0.0.0.0:19092
```

**Verification:**
```bash
# Check Redpanda is running
docker compose exec redpanda rpk cluster info

# List topics
docker compose exec redpanda rpk topic list

# Create topics manually (or let aiokafka auto-create)
docker compose exec redpanda rpk topic create ai.proposals ai.sessions ai.chat ai.workflows
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Events published to Kafka on proposal create/apply/cancel | `rpk topic consume ai.proposals` shows events |
| AC-2 | Events published on session start/end | `rpk topic consume ai.sessions` shows events |
| AC-3 | Consumer can replay from earliest offset | `rpk topic consume ai.proposals --offset oldest` |
| AC-4 | Kafka unavailable → events still persisted to DB outbox | Stop Redpanda → create proposal → check `ai_outbox` table |
| AC-5 | Kafka reconnects on restart | Start Redpanda → publisher auto-reconnects on next publish attempt |

---

## Validation

```bash
# 1. Install aiokafka
pip install aiokafka>=0.11.0

# 2. Start Redpanda (if not running)
docker compose -f docker-compose.yml up -d redpanda

# 3. Verify Redpanda
docker compose exec redpanda rpk cluster info

# 4. Create topics
docker compose exec redpanda rpk topic create ai.proposals ai.sessions ai.chat ai.workflows

# 5. Verify Python import
PYTHONPATH=. python -c "
from app.events.kafka_publisher import KafkaEventPublisher
import asyncio
async def test():
    p = KafkaEventPublisher()
    await p.start()
    ok = await p.publish('proposals', 'test.event', {'test': True})
    print(f'Published: {ok}')
    await p.stop()
asyncio.run(test())
"

# 6. Consume the test event
docker compose exec redpanda rpk topic consume ai.proposals --num 1
```
