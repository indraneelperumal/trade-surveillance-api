FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md
COPY trade_surveillance /app/trade_surveillance
COPY migrations.py /app/migrations.py
COPY mock_data_script.py /app/mock_data_script.py

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD ["uvicorn", "trade_surveillance.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
