FROM python:3.12-slim
WORKDIR /app
COPY provider/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common ./common
COPY provider/main.py .
RUN useradd -m app
USER app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
