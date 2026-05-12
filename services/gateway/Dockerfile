FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    PODIQ_SERVICE_NAME=gateway \
    LOG_FORMAT=json

WORKDIR /app

COPY services/gateway/requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt

COPY shared/podiq_logging/structlog_setup.py /app/structlog_setup.py

COPY shared/grpc/__init__.py stubs/__init__.py
COPY shared/grpc/auth/ stubs/auth/
COPY shared/grpc/analyzer/ stubs/analyzer/
COPY shared/grpc/ai/ stubs/ai/

COPY services/gateway/ .

EXPOSE 8000

CMD ["sh", "-c", "python3 manage.py migrate --noinput && python3 -m gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 180"]
