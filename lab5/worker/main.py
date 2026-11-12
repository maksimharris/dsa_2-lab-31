import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import gettempdir

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from common import broker
from common.db import accounts, metadata, operations, to_event
from worker.domain import calculate

logger = logging.getLogger(__name__)
READY_FILE = Path(gettempdir()) / "worker-ready"


async def process(engine, data):
    async with engine.begin() as db:
        query = select(operations).where(operations.c.operation_id == data["operation_id"])
        saved = (await db.execute(query)).mappings().first()
        if saved is not None:
            # Если событие не дошло до брокера, отправим сохранённый результат повторно.
            return to_event(saved)

        customer_id = data["customer_id"]
        query = select(accounts.c.balance).where(accounts.c.customer_id == customer_id)
        balance = await db.scalar(query)
        if balance is None:
            balance = 0
            await db.execute(insert(accounts).values(customer_id=customer_id, balance=0))

        amount = Decimal(data["amount"]) if "amount" in data else None
        data["amount"] = amount

        purchase = None
        already_returned = False
        applied_receipt = select(operations).where(
            operations.c.check_number == data["check_number"],
            operations.c.status == "applied",
        )
        if data["type"] in ("purchase", "return"):
            query = applied_receipt.where(operations.c.type == "purchase")
            purchase = (await db.execute(query)).mappings().first()
        if data["type"] == "return" and purchase is not None:
            query = applied_receipt.where(operations.c.type == "return")
            already_returned = (await db.execute(query)).first() is not None

        delta, reason = calculate(data, balance, purchase, already_returned)
        record = {
            "operation_id": data["operation_id"],
            "type": data["type"],
            "customer_id": customer_id,
            "store_id": data["store_id"],
            "check_number": data["check_number"],
            "amount": amount,
            "points_delta": delta,
            "balance_after": balance + delta,
            "status": "applied" if reason is None else "rejected",
            "reject_reason": reason,
            "occurred_at": datetime.fromisoformat(data["occurred_at"]),
            "processed_at": datetime.now(timezone.utc),
        }
        await db.execute(insert(operations).values(**record))
        await db.execute(
            update(accounts)
            .where(accounts.c.customer_id == customer_id)
            .values(balance=record["balance_after"])
        )
        return to_event(record)


async def main():
    READY_FILE.unlink(missing_ok=True)
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        async with engine.begin() as db:
            await db.run_sync(metadata.create_all)

        connection = await broker.connect()
        async with connection:
            channel = await connection.channel(
                publisher_confirms=True, on_return_raises=True
            )
            await channel.set_qos(prefetch_count=1)
            _, queue = await broker.operations(channel)
            exchange = await broker.events(channel)
            await broker.bind_queue(channel, exchange, "notifier.events")
            await broker.bind_queue(channel, exchange, "analytics.events")

            async with queue.iterator() as messages:
                READY_FILE.touch()
                logger.info("Waiting for operations")
                async for message in messages:
                    try:
                        data = json.loads(message.body)
                        event = await process(engine, data)
                        await broker.publish(exchange, event, "")
                    except Exception:
                        logger.exception("Operation processing failed")
                        await asyncio.sleep(1)
                        await message.nack(requeue=True)
                    else:
                        # process() уже зафиксировал транзакцию, а publish() получил confirm.
                        await message.ack()
                        logger.info("%s: %s", event["operation_id"], event["status"])
    finally:
        READY_FILE.unlink(missing_ok=True)
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
