import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Body, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from api.schemas import Purchase, Redeem, Return
from common import broker
from common.db import accounts, operations, to_event

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app):
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        connection = await broker.connect()
        async with connection:
            channel = await connection.channel(
                publisher_confirms=True, on_return_raises=True
            )
            app.state.exchange, _ = await broker.operations(channel)
            app.state.channel = channel
            app.state.engine = engine
            yield
    finally:
        await engine.dispose()


app = FastAPI(title="Loyalty API", lifespan=lifespan)


@app.post("/operations", status_code=202)
async def submit(
    operation: Annotated[Purchase | Return | Redeem, Body(discriminator="type")],
):
    payload = operation.model_dump(mode="json")
    try:
        await asyncio.wait_for(
            broker.publish(app.state.exchange, payload, "operation"), timeout=6
        )
    except Exception as error:
        logger.warning("Operation publication failed: %s", error)
        raise HTTPException(503, "RabbitMQ did not confirm the operation") from error
    return {"operation_id": operation.operation_id}


@app.get("/operations/{operation_id}")
async def result(operation_id: str):
    query = select(operations).where(operations.c.operation_id == operation_id)
    async with app.state.engine.connect() as db:
        row = (await db.execute(query)).mappings().first()
    if row is None:
        raise HTTPException(404, "Operation has not been processed")
    return to_event(row)


@app.get("/accounts/{customer_id}")
async def account(customer_id: str):
    async with app.state.engine.connect() as db:
        query = select(accounts.c.balance).where(accounts.c.customer_id == customer_id)
        balance = await db.scalar(query)
        if balance is None:
            raise HTTPException(404, "Account not found")
        query = (
            select(operations)
            .where(operations.c.customer_id == customer_id)
            .order_by(operations.c.processed_at.desc())
            .limit(20)
        )
        rows = (await db.execute(query)).mappings().all()
    return {
        "customer_id": customer_id,
        "balance": balance,
        "operations": [to_event(row) for row in rows],
    }


@app.get("/health")
async def health():
    try:
        async with asyncio.timeout(5):
            async with app.state.engine.connect() as db:
                await db.execute(select(1))
            await app.state.channel.get_queue("operations", ensure=True)
    except Exception as error:
        raise HTTPException(503, "Database or RabbitMQ unavailable") from error
    return {"status": "ok"}
