FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    PODIQ_SERVICE_NAME=auth-service \
    LOG_FORMAT=json

WORKDIR /app

COPY services/auth-service/requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt

COPY shared/podiq_logging/structlog_setup.py /app/structlog_setup.py

COPY shared/grpc/__init__.py stubs/__init__.py
COPY shared/grpc/auth/ stubs/auth/

COPY services/auth-service/ .

EXPOSE 50051

CMD ["sh", "-c", "python3 manage.py migrate --noinput && python3 -m app.grpc_server"]
