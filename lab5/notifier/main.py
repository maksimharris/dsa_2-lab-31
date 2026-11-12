import asyncio
import logging
import os
import random

from fastapi import FastAPI

from common.subscriber import event_listener

logger = logging.getLogger("uvicorn.error")
min_delay = int(os.getenv("MIN_DELAY_MS", "200"))
max_delay = int(os.getenv("MAX_DELAY_MS", "1500"))
unsubscribed = {item.strip() for item in os.getenv("UNSUBSCRIBED", "").split(",")}
notifications = {}
received = 0
sent = 0


async def notify(event):
    global received, sent
    received += 1
    customer_id = event["customer_id"]
    if customer_id in unsubscribed:
        return

    delta = event["points_delta"]
    balance = event["balance_after"]
    if event["status"] == "rejected":
        text = f"Операция отклонена: {event['reject_reason']}"
    elif event["type"] == "purchase":
        text = f"Начислено {delta} баллов, баланс {balance}"
    else:
        text = f"Списано {abs(delta)} баллов, баланс {balance}"

    await asyncio.sleep(random.randint(min_delay, max_delay) / 1000)
    logger.info("Notification for %s: %s", customer_id, text)
    notifications.setdefault(customer_id, []).append({
        "operation_id": event["operation_id"],
        "text": text,
    })
    sent += 1


app = FastAPI(title="Loyalty Notifier", lifespan=event_listener("notifier.events", notify))


@app.get("/notifications")
async def customer_notifications(customer_id: str):
    return notifications.get(customer_id, [])


@app.get("/stats")
async def stats():
    return {"received_events": received, "sent_notifications": sent}
