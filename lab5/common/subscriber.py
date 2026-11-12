import json
from contextlib import asynccontextmanager

from common import broker


def event_listener(queue_name, handle):
    @asynccontextmanager
    async def lifespan(app):
        connection = await broker.connect()
        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=1)
            exchange = await broker.events(channel)
            queue = await broker.bind_queue(channel, exchange, queue_name)
            seen = set()

            async def receive(message):
                async with message.process():
                    event = json.loads(message.body)
                    operation_id = event["operation_id"]
                    if operation_id not in seen:
                        await handle(event)
                        seen.add(operation_id)

            # consume регистрирует фоновый обработчик и возвращает управление.
            await queue.consume(receive)
            yield

    return lifespan
