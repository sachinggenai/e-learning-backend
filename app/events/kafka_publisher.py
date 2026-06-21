"""Async Kafka publisher for Redpanda — US-PEND-024."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

logger = logging.getLogger(__name__)

TOPICS = {
    "proposals": "ai.proposals",
    "sessions": "ai.sessions",
    "chat": "ai.chat",
    "workflows": "ai.workflows",
    "dead_letter": "ai.dead_letter",
}


class KafkaEventPublisher:
    """Publishes domain events to Redpanda/Kafka with graceful degradation.

    If Kafka is unavailable, events must fall back to the DB outbox
    (caller responsibility — check is_available before calling publish).
    """

    def __init__(self, bootstrap_servers: Optional[str] = None):
        self.bootstrap_servers = bootstrap_servers or os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"
        )
        self._producer: Optional[AIOKafkaProducer] = None
        self._enabled = os.getenv("KAFKA_ENABLED", "true").lower() == "true"

    async def start(self) -> None:
        if not self._enabled:
            logger.info("Kafka publisher disabled (KAFKA_ENABLED=false)")
            return
        try:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                compression_type="gzip",
            )
            await self._producer.start()
            logger.info("Kafka publisher connected to %s", self.bootstrap_servers)
        except Exception as exc:
            logger.warning("Kafka unavailable (%s) — falling back to DB outbox", exc)
            self._enabled = False

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()

    async def publish(self, domain: str, event_type: str, payload: Dict[str, Any],
                      key: Optional[str] = None) -> bool:
        if not self._enabled or not self._producer:
            return False
        topic = TOPICS.get(domain, f"ai.{domain}")
        event = {"event_type": event_type, "domain": domain, "payload": payload}
        try:
            await self._producer.send_and_wait(
                topic=topic, value=event,
                key=key.encode("utf-8") if key else None,
            )
            return True
        except KafkaError as exc:
            logger.error("Kafka publish failed: %s", exc)
            return False

    @property
    def is_available(self) -> bool:
        return self._enabled and self._producer is not None
