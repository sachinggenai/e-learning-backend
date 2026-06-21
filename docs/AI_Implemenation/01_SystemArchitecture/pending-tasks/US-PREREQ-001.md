# US-PREREQ-001: Deploy Redpanda (Kafka) via Docker for Local Development

| Field | Value |
|-------|-------|
| **Type** | 🏗️ Infrastructure Pre-Requisite |
| **Priority** | 🔴 CRITICAL — Unblocks US-PEND-024, US-PEND-025 |
| **Depends On** | Docker Desktop (running on developer machine) |
| **Estimated Effort** | 10 minutes |
| **Unblocks** | US-PEND-024 (Kafka event streaming), US-PEND-025 (RLHF feedback) |

---

## User Story

**As a** backend developer implementing event streaming,
**I want** a Kafka-compatible message broker running locally in Docker,
**So that** I can develop and test Kafka integration without provisioning a remote cluster.

---

## Intent of Work

Deploy **Redpanda** — a single-binary, Apache-2.0 licensed, Kafka-API-compatible streaming platform that requires **zero ZooKeeper dependency**. Any Kafka client library (`aiokafka`, `confluent-kafka`, `kafka-python`) works against Redpanda unchanged. Runs on Docker Desktop with 1 CPU and no special configuration.

**Why Redpanda over Apache Kafka:** Apache Kafka requires ZooKeeper (or KRaft with complex setup). Redpanda is a single `redpanda start` command. Same Kafka API, 10x lower P99 latency, S3 tiered storage.

---

## Docker Deployment

### One-Command Install

```powershell
# PowerShell — run directly on Windows
docker run -d `
  --name elearning-redpanda `
  --restart unless-stopped `
  -p 19092:19092 `
  -p 18082:18082 `
  -p 19644:9644 `
  -v redpanda_data:/var/lib/redpanda/data `
  -e "REDPANDA_MODE=dev" `
  docker.redpanda.com/redpandadata/redpanda:v24.1.1 `
  redpanda start `
    --smp 1 `
    --overprovisioned `
    --kafka-addr internal://0.0.0.0:9092,external://0.0.0.0:19092 `
    --advertise-kafka-addr internal://redpanda:9092,external://localhost:19092 `
    --pandaproxy-addr internal://0.0.0.0:8082,external://0.0.0.0:18082
```

### What Each Flag Means

| Flag | Value | Purpose |
|------|-------|---------|
| `-p 19092:19092` | Kafka API port | External Kafka protocol — connect your app to `localhost:19092` |
| `-p 18082:18082` | HTTP Proxy port | REST API for topic management, consumer groups |
| `-p 19644:9644` | Admin port | `rpk` CLI + Prometheus metrics |
| `--smp 1` | 1 CPU core | Limits resource usage on dev machine |
| `--overprovisioned` | Dev mode | Disables resource checks for Docker Desktop |
| `REDPANDA_MODE=dev` | Dev environment | Enables auto-topic-creation, relaxed timeouts |

---

## Verification

```powershell
# 1. Check Redpanda is running
docker ps --filter name=elearning-redpanda

# 2. Check cluster info
docker exec elearning-redpanda rpk cluster info
# Expected: Cluster ID, node count = 1, healthy = true

# 3. Create test topics
docker exec elearning-redpanda rpk topic create ai.proposals ai.sessions ai.chat ai.workflows
# Expected: Created topic 'ai.proposals' ... OK for all 4

# 4. List topics
docker exec elearning-redpanda rpk topic list
# Expected: 4 topics listed

# 5. Produce a test message
echo '{"event":"test","data":{"hello":"world"}}' | `
  docker exec -i elearning-redpanda rpk topic produce ai.proposals

# 6. Consume the test message
docker exec elearning-redpanda rpk topic consume ai.proposals --num 1
# Expected: { event: test, data: { hello: world } }
```

---

## Python Verification (After `pip install aiokafka>=0.11.0`)

```python
# test_kafka.py — verify Python → Redpanda connectivity
import asyncio
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
import json

async def test_produce_consume():
    # Produce
    producer = AIOKafkaProducer(
        bootstrap_servers="localhost:19092",
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    await producer.start()
    await producer.send_and_wait("ai.test", {"status": "ok"})
    await producer.stop()
    print("✅ Produce: OK")

    # Consume
    consumer = AIOKafkaConsumer(
        "ai.test",
        bootstrap_servers="localhost:19092",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
    )
    await consumer.start()
    async for msg in consumer:
        print(f"✅ Consume: {msg.value}")
        break
    await consumer.stop()

asyncio.run(test_produce_consume())
```

---

## Teardown

```powershell
# Stop and remove the container (data preserved in volume)
docker stop elearning-redpanda
docker rm elearning-redpanda

# Also remove the data volume (fresh start)
docker volume rm redpanda_data
```

---

## Environment Variables (add to `.env`)

```bash
# Redpanda / Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:19092
KAFKA_ENABLED=true
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Redpanda container running and healthy | `docker exec elearning-redpanda rpk cluster info \| grep healthy` |
| AC-2 | Kafka API reachable on `localhost:19092` | Python test script produces + consumes successfully |
| AC-3 | Topics created | `rpk topic list` shows created topics |
| AC-4 | Container restarts automatically | `docker restart elearning-redpanda` → still running after |

---

## Stories Unblocked

Once this pre-requisite is complete, these stories become implementable locally:

| Story | What It Needs Kafka For |
|-------|------------------------|
| **US-PEND-024** | `KafkaEventPublisher` — publish events to `ai.proposals`, `ai.sessions`, `ai.chat`, `ai.workflows` topics |
| **US-PEND-025** | RLHF feedback events flow through Kafka → analytics consumers |
