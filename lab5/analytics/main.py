from fastapi import FastAPI, HTTPException

from common.subscriber import event_listener

stores = {}
received = 0


async def record(event):
    global received
    received += 1
    store_id = event["store_id"]
    stats = stores.setdefault(store_id, {
        "store_id": store_id,
        "purchases": 0,
        "returns": 0,
        "redeems": 0,
        "rejected": 0,
        "earned_points": 0,
        "returned_points": 0,
        "redeemed_points": 0,
    })

    points = abs(event["points_delta"])
    if event["status"] == "rejected":
        stats["rejected"] += 1
    elif event["type"] == "purchase":
        stats["purchases"] += 1
        stats["earned_points"] += points
    elif event["type"] == "return":
        stats["returns"] += 1
        stats["returned_points"] += points
    else:
        stats["redeems"] += 1
        stats["redeemed_points"] += points


app = FastAPI(title="Loyalty Analytics", lifespan=event_listener("analytics.events", record))


@app.get("/stores")
async def all_stores():
    return list(stores.values())


@app.get("/stores/{store_id}")
async def one_store(store_id: str):
    if store_id not in stores:
        raise HTTPException(404, "Store not found")
    return stores[store_id]


@app.get("/stats")
async def stats():
    return {"received_events": received}
