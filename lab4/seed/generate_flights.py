import os
import random
import sys 
from datetime import datetime, timedelta
from pathlib import Path

import psycopg 

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.airports import AIRPORTS

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/flights"
)
START_DATE = datetime.fromisoformat(os.environ.get("START_DATE", "2026-11-01"))
DAYS = 120               # п. 2: генерировать на 120 дней
FLIGHTS_PER_DAY = 1500   # условие: 1500 рейсов в сутки
SEED = 42                # постоянное начальное значение
CARRIERS = ["SU", "S7", "U6", "DP", "FV"]

def generate_flights():
    rng = random.Random(SEED)
    for day in range(DAYS):
        day_start = START_DATE + timedelta(days=day)
        for _ in range(FLIGHTS_PER_DAY):
            origin, destination = rng.sample(AIRPORTS, 2)  # два разных аэропорта
            departure = day_start + timedelta(minutes=rng.randrange(24 * 60))
            duration = timedelta(minutes=rng.randint(60, 6 * 60))  # от 1 до 6 часов
            carrier = rng.choice(CARRIERS)
            flight_no = f"{carrier}{rng.randint(100, 9999)}"
            price = rng.randrange(2000, 25000, 50)
            yield (carrier, flight_no, origin, destination,
                   departure, departure + duration, price)

def main():
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(schema)
        conn.execute("TRUNCATE flights RESTART IDENTITY")
        with conn.cursor() as cur:
            # COPY - самый быстрый способ загрузки большого объёма (п. 3)
            with cur.copy(
                "COPY flights (carrier, flight_no, origin, destination,"
                " departure_time, arrival_time, price) FROM STDIN"
            ) as copy:
                for row in generate_flights():
                    copy.write_row(row)
        conn.execute("ANALYZE flights")  # статистика для планировщика
        count = conn.execute("SELECT count(*) FROM flights").fetchone()[0]
    print(f"Загружено рейсов: {count}")