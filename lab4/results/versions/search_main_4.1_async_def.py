"""Задача 3.3: синхронная версия сервиса поиска.

Всё блокирующее: requests, time.sleep, SQLAlchemy Core + psycopg.
Обработчики объявлены через def, поэтому FastAPI выполняет каждый запрос
в своём потоке из пула (40 потоков по умолчанию, раздел 4 ЛР4_доп).
"""
import os
import sys
import time
from datetime import date as Date, datetime, timedelta
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import create_engine, text

from routes import Flight, build_routes, select_top

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.airports import AIRPORTS  # noqa: E402

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/flights"
)
# "provider1=http://provider1:8000,provider2=http://provider2:8000,..."
PROVIDERS = dict(
    item.split("=", 1)
    for item in os.environ.get(
        "PROVIDERS",
        "provider1=http://localhost:8001,provider2=http://localhost:8002,"
        "provider3=http://localhost:8003",
    ).split(",")
)
PROVIDER_TIMEOUT_S = 2.0   # на каждого поставщика 2 с, включая повторный запрос
RETRY_PAUSE_S = 0.2        # пауза перед повтором 200 мс

# п. 3: синхронный движок SQLAlchemy Core, драйвер psycopg (postgresql+psycopg).
# pool_size=40 равен числу потоков, чтобы потоки не ждали свободного соединения.
engine = create_engine(DATABASE_URL, pool_size=40, max_overflow=0)

app = FastAPI(title="Сервис поиска (синхронный)")


def load_own_flights(search_date: Date) -> list[Flight]:
    """Чтение рейсов за дату из собственной БД (операция "ожидание БД")."""
    day_start = datetime.combine(search_date, datetime.min.time())
    query = text(
        "SELECT carrier, flight_no, origin, destination,"
        "       departure_time, arrival_time, price "
        "FROM flights "
        "WHERE departure_time >= :start AND departure_time < :end"
    )
    # Соединение держится только на время запроса (with ... connect()),
    # это важно для расчёта по закону Литтла (задача 2.3, п. 2).
    with engine.connect() as conn:
        rows = conn.execute(
            query, {"start": day_start, "end": day_start + timedelta(days=1)}
        ).all()
    return [Flight(r.carrier, r.flight_no, r.origin.strip(), r.destination.strip(),
                   r.departure_time, r.arrival_time, float(r.price)) for r in rows]


def parse_flight(item: dict) -> Flight:
    return Flight(item["carrier"], item["flight_no"], item["origin"],
                  item["destination"],
                  datetime.fromisoformat(item["departure_time"]),
                  datetime.fromisoformat(item["arrival_time"]),
                  float(item["price"]))


def fetch_provider(url: str, search_date: Date) -> list[Flight] | None:
    """Запрос рейсов у одного поставщика. None - поставщик не ответил.

    2 секунды отсчитываются от первого запроса. Повтор входит в те же 2 секунды:
    его тайм-аут равен оставшемуся времени, а сам повтор выполняется, только если
    после паузы 200 мс время ещё осталось (раздел 9 ЛР4_доп).
    """
    started = time.monotonic()
    for attempt in range(2):                     # первый запрос + один повтор
        remaining = PROVIDER_TIMEOUT_S - (time.monotonic() - started)
        if remaining <= 0:
            return None
        try:
            # п. 2: блокирующий вызов requests (поток стоит, пока ждёт ответ)
            resp = requests.get(f"{url}/flights", params={"date": search_date.isoformat()},
                                timeout=remaining)
            resp.raise_for_status()              # ответ 500 -> исключение
            return [parse_flight(i) for i in resp.json()["flights"]]
        except requests.Timeout:
            return None                          # время вышло, повторять нечего
        except requests.RequestException:        # ошибка 500 или сбой соединения
            if attempt == 0:
                time.sleep(RETRY_PAUSE_S)        # п. 2: пауза через time.sleep
    return None


@app.get("/search")
async def search(origin: str, destination: str,
                 search_date: Date = Query(alias="date")):
    # Задача 4.1, п. 1: теперь async def. Обработчик исполняется ПРЯМО в цикле
    # событий, а внутри остались блокирующие вызовы (requests, time.sleep, psycopg).
    started = time.perf_counter()
    if origin not in AIRPORTS or destination not in AIRPORTS:
        raise HTTPException(status_code=422, detail="Неизвестный аэропорт")

    flights = load_own_flights(search_date)
    own_found = bool(flights)

    # п. 2: поставщики опрашиваются по очереди - время ответа складывается.
    failed = []
    for name, url in PROVIDERS.items():
        provider_flights = fetch_provider(url, search_date)
        if provider_flights is None:
            failed.append(name)
        else:
            flights.extend(provider_flights)

    # Не ответил ни один поставщик и в своей базе нет рейсов на дату.
    if len(failed) == len(PROVIDERS) and not own_found:
        raise HTTPException(status_code=503, detail="Поиск временно недоступен")

    routes = select_top(build_routes(flights, origin, destination, search_date))
    return {
        "routes": [
            {"price": r.price,
             "flights": [{"carrier": f.carrier, "flight_no": f.flight_no,
                          "origin": f.origin, "destination": f.destination,
                          "departure_time": f.departure_time.isoformat(),
                          "arrival_time": f.arrival_time.isoformat(),
                          "price": f.price} for f in r.flights]}
            for r in routes
        ],
        "failed_providers": failed,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


@app.get("/health")
async def health():
    # п. 1: проверка работоспособности (используется docker healthcheck).
    return {"status": "ok"}
