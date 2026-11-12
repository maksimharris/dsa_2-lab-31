FROM python:3.12-slim AS builder
COPY analytics/requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN useradd --create-home app
COPY --from=builder /opt/venv /opt/venv
COPY common/ common/
COPY analytics/ analytics/
USER app
EXPOSE 8002
CMD ["uvicorn", "analytics.main:app", "--host", "0.0.0.0", "--port", "8002"]
