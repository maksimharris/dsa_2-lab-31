CREATE TABLE IF NOT EXISTS flights (
    id             BIGSERIAL PRIMARY KEY,
    carrier        VARCHAR(8)     NOT NULL,  -- перевозчик
    flight_no      VARCHAR(16)    NOT NULL,  -- номер рейса
    origin         CHAR(3)        NOT NULL,  -- аэропорт вылета
    destination    CHAR(3)        NOT NULL,  -- аэропорт прилёта
    departure_time TIMESTAMP      NOT NULL,  -- время вылета
    arrival_time   TIMESTAMP      NOT NULL,  -- время прилёта
    price          NUMERIC(10, 2) NOT NULL   -- цена
);

-- Сервис всегда спрашивает "рейсы с 00:00 до 24:00 заданной даты",
CREATE INDEX IF NOT EXISTS idx_flights_departure_time
    ON flights (departure_time);