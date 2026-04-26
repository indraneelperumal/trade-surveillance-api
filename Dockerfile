# Trade Surveillance API — production-style image (Render, Fly, etc.)
FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml README.md ./
COPY trade_surveillance ./trade_surveillance

RUN pip install --upgrade pip && pip install .

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn trade_surveillance.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
