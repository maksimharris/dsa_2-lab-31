import argparse
import asyncio
import json
import math
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.airports import AIRPORTS  # noqa: E402

DAYS = 120  # рейсы в базе есть на 120 дней от START_DATE


def percentile(sorted_values: list[float], p: float) -> float:

    if not sorted_values:
        return float("nan")
    rank = math.ceil(p / 100 * len(sorted_values))
    return sorted_values[max(rank, 1) - 1]


def make_queries(seed: int, start_date: date, count: int = 200_000):

    rng = random.Random(seed)
    for _ in range(count):
        origin, destination = rng.sample(AIRPORTS, 2)
        day = start_date + timedelta(days=rng.randrange(DAYS))
        yield {"origin": origin, "destination": destination, "date": day.isoformat()}


async def timed_get(client: httpx.AsyncClient, url: str, params=None):
    """Один запрос. Ошибка - код 4xx/5xx или отсутствие ответа за тайм-аут клиента."""
    began = time.perf_counter()
    try:
        resp = await client.get(url, params=params)
        ok = resp.status_code < 400
    except httpx.HTTPError:          # включая httpx.TimeoutException
        ok = False
    return began, time.perf_counter() - began, ok


async def run(args) -> dict:
    limits = httpx.Limits(max_connections=2000, max_keepalive_connections=2000)
    timeout = httpx.Timeout(args.timeout)
    queries = make_queries(args.seed, date.fromisoformat(args.start_date))
    search_url = f"{args.url}/search"
    health_url = f"{args.url}/health"

    search_results, health_results = [], []

    # /health опрашивается отдельным клиентом, чтобы его соединения не зависели
    # от пула нагрузки.
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client, \
            httpx.AsyncClient(timeout=timeout) as health_client:
.
        t0 = time.perf_counter()
        measure_start = t0 + args.warmup       # запросы прогрева не учитываются
        stop_at = measure_start + args.duration

        async def closed_client():
            while time.perf_counter() < stop_at:
                search_results.append(
                    await timed_get(client, search_url, next(queries)))

        async def open_loop():

            arrivals = random.Random(args.seed + 1)
            pending = set()

            async def send(params):
                search_results.append(await timed_get(client, search_url, params))

            while time.perf_counter() < stop_at:
                task = asyncio.create_task(send(next(queries)))
                pending.add(task)
                task.add_done_callback(pending.discard)
                await asyncio.sleep(arrivals.expovariate(args.rate))
            await asyncio.gather(*pending)

        async def health_poller():
            pending, next_tick = set(), time.perf_counter()
            async def ping():
                health_results.append(await timed_get(health_client, health_url))
            while time.perf_counter() < stop_at:
                task = asyncio.create_task(ping())
                pending.add(task)
                task.add_done_callback(pending.discard)
                next_tick += 0.1
                await asyncio.sleep(max(0.0, next_tick - time.perf_counter()))
            await asyncio.gather(*pending)

        if args.mode == "closed":
            load = [closed_client() for _ in range(args.clients)]
        else:
            load = [open_loop()]
        await asyncio.gather(*load, health_poller())

    def summarize(results):
        # Учитываются только запросы, отправленные после прогрева.
        window = [r for r in results if r[0] >= measure_start]
        durations = sorted(r[1] * 1000 for r in window)
        errors = sum(1 for r in window if not r[2])
        n = len(window)
        return {
            "requests": n,
            "rps": round(n / args.duration, 2),
            "p50_ms": round(percentile(durations, 50), 1),
            "p95_ms": round(percentile(durations, 95), 1),
            "p99_ms": round(percentile(durations, 99), 1),
            "max_ms": round(durations[-1], 1) if durations else float("nan"),
            "errors_percent": round(100 * errors / n, 2) if n else float("nan"),
        }

    return {"search": summarize(search_results), "health": summarize(health_results)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--mode", choices=["closed", "open"], required=True)
    p.add_argument("--clients", type=int, default=10, help="C для замкнутого режима")
    p.add_argument("--rate", type=float, default=5, help="запросов/с для открытого режима")
    p.add_argument("--duration", type=float, default=60, help="длительность замера, с")
    p.add_argument("--warmup", type=float, default=10, help="прогрев, с")
    p.add_argument("--timeout", type=float, default=30, help="тайм-аут клиента, с")
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--start-date", default="2026-11-01")
    p.add_argument("--json", help="сохранить результат в JSON-файл")
    args = p.parse_args()

    result = asyncio.run(run(args))

    print(f"Режим: {args.mode}, "
          + (f"C={args.clients}" if args.mode == "closed" else f"{args.rate} зап/с")
          + f", замер {args.duration:g} с, прогрев {args.warmup:g} с")
    print(f"{'':8}{'запросов':>9}{'зап/с':>8}{'p50':>9}{'p95':>9}{'p99':>9}"
          f"{'макс':>9}{'ошибки %':>10}")
    for name in ("search", "health"):
        r = result[name]
        print(f"{name:8}{r['requests']:>9}{r['rps']:>8}{r['p50_ms']:>9}"
              f"{r['p95_ms']:>9}{r['p99_ms']:>9}{r['max_ms']:>9}{r['errors_percent']:>10}")
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                   encoding="utf-8")


if __name__ == "__main__":
    main()
