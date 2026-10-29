FROM python:3.12-slim
WORKDIR /app
COPY search/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common ./common
COPY search/*.py .
# Приложение работает от обычного пользователя (ЛР №1), py-spy запускается от root.
RUN useradd -m app
USER app
# Задача 3.4, п. 2 и п. 4: один worker; exec делает uvicorn процессом с PID 1,
# чтобы py-spy мог подключиться к нему командой --pid 1 (раздел 8 ЛР4_доп).
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1"]
