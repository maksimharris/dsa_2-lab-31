import json
import os

import aio_pika


async def connect():
    return await aio_pika.connect_robust(os.environ["RABBITMQ_URL"], timeout=5)


async def bind_queue(channel, exchange, name, key=""):
    queue = await channel.declare_queue(
        name, durable=True, arguments={"x-queue-type": "quorum"}
    )
    await queue.bind(exchange, routing_key=key)
    return queue


async def operations(channel):
    exchange = await channel.declare_exchange(
        "loyalty", aio_pika.ExchangeType.DIRECT, durable=True
    )
    queue = await bind_queue(channel, exchange, "operations", "operation")
    return exchange, queue


async def events(channel):
    return await channel.declare_exchange(
        "loyalty.events", aio_pika.ExchangeType.FANOUT, durable=True
    )


async def publish(exchange, payload, key):
    message = aio_pika.Message(
        body=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        message_id=payload["operation_id"],
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )
    confirmed = await exchange.publish(
        message, routing_key=key, mandatory=True, timeout=5
    )
    if not confirmed:
        raise RuntimeError("RabbitMQ did not confirm the publication")
