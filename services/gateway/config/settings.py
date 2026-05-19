import os
from urllib.parse import urlparse

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,gateway"
).split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "corsheaders",
    "core",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"

_db = urlparse(os.environ["DATABASE_URL"])
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _db.path.lstrip("/"),
        "USER": _db.username,
        "PASSWORD": _db.password,
        "HOST": _db.hostname,
        "PORT": _db.port or 5432,
    }
}

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

# Internal gRPC service endpoints
AUTH_GRPC_HOST = os.environ.get("AUTH_GRPC_HOST", "auth-service")
AUTH_GRPC_PORT = int(os.environ.get("AUTH_GRPC_PORT", "50051"))
ANALYZER_GRPC_HOST = os.environ.get("ANALYZER_GRPC_HOST", "analyzer-service")
ANALYZER_GRPC_PORT = int(os.environ.get("ANALYZER_GRPC_PORT", "50052"))
AI_GRPC_HOST = os.environ.get("AI_GRPC_HOST", "ai-service")
AI_GRPC_PORT = int(os.environ.get("AI_GRPC_PORT", "50053"))

CORRELATION_WINDOW_MINUTES = int(os.environ.get("CORRELATION_WINDOW_MINUTES", "15"))
CORRELATION_WINDOW_SECONDS = CORRELATION_WINDOW_MINUTES * 60

# JWT secrets for workspace-scoped tokens (signed by gateway, not auth-service)
GATEWAY_JWT_SECRET = os.environ.get("GATEWAY_JWT_SECRET", "")
GATEWAY_JWT_ACCESS_EXPIRY_MINUTES = int(
    os.environ.get("GATEWAY_JWT_ACCESS_EXPIRY_MINUTES", "60")
)
GATEWAY_REFRESH_SECRET = os.environ.get("GATEWAY_REFRESH_SECRET", "")
GATEWAY_REFRESH_EXPIRY_DAYS = int(os.environ.get("GATEWAY_REFRESH_EXPIRY_DAYS", "30"))

# CORS — credentials required for httpOnly cookie support
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ALLOWED_ORIGINS", "http://localhost:4200,http://localhost:8080"
    ).split(",")
    if o.strip()
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

import structlog_setup

structlog_setup.configure_podiq_logging()
