FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    PODIQ_SERVICE_NAME=analyzer-service \
    LOG_FORMAT=json

WORKDIR /app

COPY services/analyzer-service/requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt

COPY shared/podiq_logging/structlog_setup.py /app/structlog_setup.py

COPY shared/grpc/__init__.py stubs/__init__.py
COPY shared/grpc/analyzer/ stubs/analyzer/

COPY services/analyzer-service/ .

EXPOSE 50052

CMD ["sh", "-c", "python3 manage.py migrate --noinput && python3 -m app.grpc_server"]
