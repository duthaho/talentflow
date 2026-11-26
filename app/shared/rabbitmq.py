"""Confirmed, persistent AMQP transport and ADR 006 topology."""

import json
from datetime import datetime

import pika

RETRY_DELAYS = (10000, 60000, 600000)


class RabbitBroker:
    def __init__(
        self,
        url: str,
        *,
        consumer: str = "notifications",
        bindings: tuple[str, ...] = ("offer.approval_recorded.v1",),
    ):
        self.url = url
        self.consumer = consumer
        self.bindings = bindings
        self.connection = None
        self.channel = None

    def connect(self) -> None:
        if (
            self.connection is not None
            and self.connection.is_open
            and self.channel is not None
            and self.channel.is_open
        ):
            return
        params = pika.URLParameters(self.url)
        params.socket_timeout = 5
        params.stack_timeout = 10
        params.blocked_connection_timeout = 5
        params.heartbeat = 120
        self.connection = pika.BlockingConnection(params)
        self.channel = self.connection.channel()
        self.channel.confirm_delivery()
        self.declare_topology()

    def declare_topology(self) -> None:
        ch = self.channel
        c = self.consumer
        ch.exchange_declare("talentflow.unrouted", exchange_type="fanout", durable=True)
        ch.queue_declare("talentflow.unrouted", durable=True, arguments={"x-queue-type": "quorum"})
        ch.queue_bind("talentflow.unrouted", "talentflow.unrouted")
        ch.exchange_declare(
            "talentflow.events",
            exchange_type="topic",
            durable=True,
            arguments={"alternate-exchange": "talentflow.unrouted"},
        )
        for name in ("talentflow.retry", "talentflow.dead-letter"):
            ch.exchange_declare(name, exchange_type="direct", durable=True)
        ch.queue_declare(
            f"{c}.events",
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-dead-letter-exchange": "talentflow.dead-letter",
                "x-dead-letter-routing-key": c,
                "x-delivery-limit": 10,
                "x-dead-letter-strategy": "at-least-once",
                "x-overflow": "reject-publish",
            },
        )
        for key in self.bindings:
            ch.queue_bind(f"{c}.events", "talentflow.events", routing_key=key)
        for attempt, delay in enumerate(RETRY_DELAYS, 1):
            key = f"{c}.retry.{attempt}"
            ch.queue_declare(
                key,
                durable=True,
                arguments={
                    "x-queue-type": "quorum",
                    "x-message-ttl": delay,
                    "x-dead-letter-exchange": "",
                    "x-dead-letter-routing-key": f"{c}.events",
                    "x-dead-letter-strategy": "at-least-once",
                    "x-overflow": "reject-publish",
                },
            )
            ch.queue_bind(key, "talentflow.retry", routing_key=key)
        ch.queue_declare(f"{c}.dlq", durable=True, arguments={"x-queue-type": "quorum"})
        ch.queue_bind(f"{c}.dlq", "talentflow.dead-letter", routing_key=c)
        ch.basic_qos(prefetch_count=10)

    def publish_event(self, event: dict) -> None:
        properties = pika.BasicProperties(
            content_type="application/cloudevents+json",
            content_encoding="utf-8",
            delivery_mode=2,
            message_id=event["id"],
            type=event["type"],
            correlation_id=event["correlationid"],
            app_id="talentflow",
            timestamp=int(datetime.fromisoformat(event["time"]).timestamp()),
        )
        self.publish("talentflow.events", event["type"], json.dumps(event).encode(), properties)

    def publish(self, exchange: str, key: str, body: bytes, properties) -> None:
        self.connect()
        # BlockingChannel waits for Basic.Ack; a nack/return raises, leaving DB/ack untouched.
        self.channel.basic_publish(
            exchange=exchange, routing_key=key, body=body, properties=properties, mandatory=True
        )

    def get(self):
        self.connect()
        self.connection.process_data_events(time_limit=0)
        return self.channel.basic_get(f"{self.consumer}.events", auto_ack=False)

    def ack(self, tag: int) -> None:
        self.channel.basic_ack(tag)

    def requeue(self, tag: int) -> None:
        if self.channel is not None and self.channel.is_open:
            self.channel.basic_nack(tag, requeue=True)

    def depths(self) -> dict[str, int]:
        self.connect()
        return {
            queue: self.channel.queue_declare(queue, passive=True).method.message_count
            for queue in (f"{self.consumer}.events", f"{self.consumer}.dlq", "talentflow.unrouted")
        }

    def close(self) -> None:
        if self.connection is not None and self.connection.is_open:
            self.connection.close()
        self.connection = self.channel = None
