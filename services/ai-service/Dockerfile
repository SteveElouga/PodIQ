FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

COPY services/ai-service/requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt

COPY shared/grpc/__init__.py stubs/__init__.py
COPY shared/grpc/ai/ stubs/ai/

COPY services/ai-service/ .

EXPOSE 50053

CMD ["sh", "-c", "python3 manage.py migrate --noinput && python3 -m app.grpc_server"]
