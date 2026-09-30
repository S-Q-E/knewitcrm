FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend ./backend
COPY frontend-legacy ./frontend-legacy

EXPOSE 8000

# Railway passes $PORT automatically
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}