
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import heapq

MIN_TRANSFER = timedelta(hours=1)   # время между рейсами от 1 ...
MAX_TRANSFER = timedelta(hours=6)   # ... до 6 часов
MAX_FLIGHTS = 3                     # прямой или не более 2 пересадок = до 3 рейсов
TOP_N = 20


@dataclass(frozen=True)
class Flight:
    carrier: str
    flight_no: str
    origin: str
    destination: str
    departure_time: datetime
    arrival_time: datetime
    price: float


@dataclass(frozen=True)
class Route:
    flights: tuple

    @property
    def price(self) -> float:
        # Стоимость маршрута = сумма цен рейсов.
        return sum(f.price for f in self.flights)


def build_routes(flights: list[Flight], origin: str, destination: str,
                 search_date: date) -> list[Route]:
    """Все маршруты origin -> destination: прямые и с не более чем 2 пересадками."""
    if origin == destination:
        return []

    # Группируем рейсы по аэропорту вылета и сортируем по времени вылета.
    # Все рейсы маршрута вылетают в дату поиска, поэтому прочие отбрасываем.
    by_origin = defaultdict(list)
    for f in flights:
        if f.departure_time.date() == search_date:
            by_origin[f.origin].append(f)
    departures = {}
    for airport, lst in by_origin.items():
        lst.sort(key=lambda f: f.departure_time)
        departures[airport] = [f.departure_time for f in lst]

    routes: list[Route] = []

    def extend(chain: tuple, visited: frozenset):
        last = chain[-1]
        candidates = by_origin.get(last.destination, [])
        times = departures.get(last.destination, [])
        # Пересадка: следующий рейс вылетает из аэропорта прилёта предыдущего,
        # через 1-6 часов после прилёта. Рейсы отсортированы по вылету, поэтому
        # bisect сразу находит первый подходящий, а перебор идёт до окна в 6 часов.
        start = bisect_left(times, last.arrival_time + MIN_TRANSFER)
        latest = last.arrival_time + MAX_TRANSFER
        for nxt in candidates[start:]:
            if nxt.departure_time > latest:
                break
            if nxt.destination in visited:      # аэропорты не повторяются
                continue
            new_chain = chain + (nxt,)
            if nxt.destination == destination:  # маршрут готов, дальше не летим
                routes.append(Route(new_chain))
            elif len(new_chain) < MAX_FLIGHTS:
                extend(new_chain, visited | {nxt.destination})

    for first in by_origin.get(origin, []):
        if first.destination == destination:    # прямой рейс
            routes.append(Route((first,)))
        elif first.destination != origin:
            extend((first,), frozenset({origin, first.destination}))
    return routes


def select_top(routes: list[Route], n: int = TOP_N) -> list[Route]:
    """n самых дешёвых маршрутов. При равной цене порядок фиксирован по рейсам."""
    return heapq.nsmallest(
        n, routes,
        key=lambda r: (r.price, [(f.departure_time, f.flight_no) for f in r.flights]),
    )
