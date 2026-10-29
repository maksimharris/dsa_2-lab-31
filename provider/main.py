import asyncio
import os
import random
import sys
from datetime import date as Date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.airports import AIRPORTS  

PROVIDER_ID = os.environ.get("PROVIDER_ID", "1")
MEAN_DELAY_MS = float(os.environ.get("MEAN_DELAY_MS", "300"))      # средняя задержка
DELAY_SPREAD = float(os.environ.get("DELAY_SPREAD", "0.3"))        # разброс ±30 %
ERROR_PERCENT = float(os.environ.get("ERROR_PERCENT", "5"))        # ответы 500, %
SLOW_PERCENT = float(os.environ.get("SLOW_PERCENT", "0"))          # ответы через 3 с, %
SLOW_DELAY_S = float(os.environ.get("SLOW_DELAY_S", "3"))          #на сколько секунд задерживается «медленный» ответ
FLIGHTS_PER_DAY = int(os.environ.get("FLIGHTS_PER_DAY", "500"))

app = FastAPI(title=f"Поставщик {PROVIDER_ID}")

@lru_cache(maxsize=256)
def generate_flights(provider_id: str, flight_date: str) -> list[dict]:
    """п. 2: рейсы генерируются при запросе, для одной даты они всегда одинаковы.

    Начальное значение генератора зависит от номера поставщика и даты
    (раздел 9 ЛР4_доп): одна и та же пара даёт один и тот же набор рейсов.
    Строка как seed даёт одинаковый результат при каждом запуске процесса.
    lru_cache лишь экономит процессор: результат для даты не меняется.
    """
    rng = random.Random(f"{provider_id}-{flight_date}")
    day_start = datetime.fromisoformat(flight_date)
    carrier = f"P{provider_id}"
    flights = []
    for i in range(FLIGHTS_PER_DAY):
        origin, destination = rng.sample(AIRPORTS, 2)
        departure = day_start + timedelta(minutes=rng.randrange(24 * 60))
        arrival = departure + timedelta(minutes=rng.randint(60, 6 * 60))
        flights.append({
            "carrier": carrier,
            "flight_no": f"{carrier}{100 + i}",
            "origin": origin,
            "destination": destination,
            "departure_time": departure.isoformat(),
            "arrival_time": arrival.isoformat(),
            "price": rng.randrange(2000, 25000, 50),
        })
    return flights
@app.get("/flights")
async def get_flights(date: Date):
    if random.random() * 100 < SLOW_PERCENT:
        delay = SLOW_DELAY_S
    else:
        delay = random.uniform(
            MEAN_DELAY_MS * (1 - DELAY_SPREAD), MEAN_DELAY_MS * (1 + DELAY_SPREAD)
        ) / 1000
    await asyncio.sleep(delay)

    if random.random() * 100 < ERROR_PERCENT:
        raise HTTPException(status_code=500, detail="Ошибка поставщика")

    return {"provider": PROVIDER_ID,
            "flights": generate_flights(PROVIDER_ID, date.isoformat())}


@app.get("/health")
async def health():
    # п. 4: всегда отвечает успешно, используется для проверки готовности.
    return {"status": "ok"}
