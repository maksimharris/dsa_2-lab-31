FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]==3.2.3"
COPY common ./common
COPY seed ./seed
CMD ["python", "seed/generate_flights.py"]
