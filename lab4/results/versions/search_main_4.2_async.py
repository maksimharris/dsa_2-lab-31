"""Задача 4.2: полностью асинхронная версия сервиса поиска.

Что изменилось по сравнению с 3.3 / 4.1 (раздел 4 и таблица 3 ЛР4_доп):
  requests.get          -> await client.get       (httpx.AsyncClient)
  time.sleep            -> await asyncio.sleep
  create_engine/psycopg -> create_async_engine/asyncpg, await conn.execute
  опрос по очереди      -> asyncio.gather (поставщики и БД одновременно)
  тайм-аут requests     -> asyncio.timeout
"""
import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import date as Date, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from routes import Flight, build_routes, select_top

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.airports import AIRPORTS  # noqa: E402

# Для асинхронного движка строка подключения содержит драйвер asyncpg.
DATABASE_URL = os.environ.get(
    "DATABASE_URL_ASYNC",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/flights",
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # п. 1: клиент и движок создаются ОДИН раз при запуске приложения.
    # Они хранят пулы открытых соединений; если создавать их в каждом запросе,
    # соединения устанавливались бы заново и выигрыш от асинхронности пропал бы.
    app.state.client = httpx.AsyncClient(
        # свой тайм-аут httpx больше 2 с: 2 секунды ограничивает asyncio.timeout
        timeout=httpx.Timeout(10.0),
        limits=httpx.Limits(max_connections=500, max_keepalive_connections=100),
    )
    app.state.engine = create_async_engine(DATABASE_URL, pool_size=20, max_overflow=20)
    yield
    await app.state.client.aclose()      # при остановке закрываем пулы
    await app.state.engine.dispose()


app = FastAPI(title="Сервис поиска (асинхронный)", lifespan=lifespan)


async def load_own_flights(engine: AsyncEngine, search_date: Date) -> list[Flight]:
    """Чтение рейсов за дату из собственной БД. await отдаёт управление циклу
    событий, пока БД выполняет запрос."""
    day_start = datetime.combine(search_date, datetime.min.time())
    query = text(
        "SELECT carrier, flight_no, origin, destination,"
        "       departure_time, arrival_time, price "
        "FROM flights "
        "WHERE departure_time >= :start AND departure_time < :end"
    )
    async with engine.connect() as conn:       # соединение занято только на время запроса
        result = await conn.execute(
            query, {"start": day_start, "end": day_start + timedelta(days=1)}
        )
        rows = result.all()
    return [Flight(r.carrier, r.flight_no, r.origin.strip(), r.destination.strip(),
                   r.departure_time, r.arrival_time, float(r.price)) for r in rows]


def parse_flight(item: dict) -> Flight:
    return Flight(item["carrier"], item["flight_no"], item["origin"],
                  item["destination"],
                  datetime.fromisoformat(item["departure_time"]),
                  datetime.fromisoformat(item["arrival_time"]),
                  float(item["price"]))


async def fetch_provider(client: httpx.AsyncClient, url: str,
                         search_date: Date) -> list[Flight] | None:
    """Запрос рейсов у одного поставщика. None - поставщик не ответил.

    asyncio.timeout(2) ограничивает ВЕСЬ блок: первый запрос, паузу и повтор.
    Если время вышло, выбрасывается TimeoutError, и поставщик считается не
    ответившим. Это то же правило, что в синхронной версии: повтор выполняется,
    только пока осталось время из тех же 2 секунд.
    """
    try:
        async with asyncio.timeout(PROVIDER_TIMEOUT_S):
            for attempt in range(2):               # первый запрос + один повтор
                try:
                    resp = await client.get(f"{url}/flights",
                                            params={"date": search_date.isoformat()})
                    resp.raise_for_status()        # ответ 500 -> исключение
                    return [parse_flight(i) for i in resp.json()["flights"]]
                except httpx.HTTPError:            # ошибка 500 или сбой соединения
                    if attempt == 0:
                        await asyncio.sleep(RETRY_PAUSE_S)   # п. 3: asyncio.sleep
    except TimeoutError:
        pass
    return None


@app.get("/search")
async def search(request: Request, origin: str, destination: str,
                 search_date: Date = Query(alias="date")):
    started = time.perf_counter()
    if origin not in AIRPORTS or destination not in AIRPORTS:
        raise HTTPException(status_code=422, detail="Неизвестный аэропорт")

    client = request.app.state.client
    engine = request.app.state.engine
    names = list(PROVIDERS)

    # п. 2: БД и все три поставщика опрашиваются ОДНОВРЕМЕННО. Общее время
    # определяется самым медленным, а не суммой.
    # return_exceptions=True: исключение одного не прерывает остальных, а
    # возвращается в списке результатов на месте своей корутины.
    results = await asyncio.gather(
        load_own_flights(engine, search_date),
        *[fetch_provider(client, PROVIDERS[n], search_date) for n in names],
        return_exceptions=True,
    )

    own_result, provider_results = results[0], results[1:]
    if isinstance(own_result, Exception):
        raise own_result                      # без собственной БД продолжать нельзя
    flights = own_result
    own_found = bool(flights)

    failed = []
    for name, res in zip(names, provider_results):
        if isinstance(res, Exception) or res is None:
            failed.append(name)
        else:
            flights.extend(res)

    # Не ответил ни один поставщик и в своей базе нет рейсов на дату.
    if len(failed) == len(names) and not own_found:
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
    return {"status": "ok"}
