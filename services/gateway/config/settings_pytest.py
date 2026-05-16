import os

SECRET_KEY = "pytest-gateway-secret-not-for-production"
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "gateway"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "corsheaders",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

AUTH_GRPC_HOST = os.environ.get("AUTH_GRPC_HOST", "auth-service")
AUTH_GRPC_PORT = int(os.environ.get("AUTH_GRPC_PORT", "50051"))
ANALYZER_GRPC_HOST = os.environ.get("ANALYZER_GRPC_HOST", "analyzer-service")
ANALYZER_GRPC_PORT = int(os.environ.get("ANALYZER_GRPC_PORT", "50052"))
AI_GRPC_HOST = os.environ.get("AI_GRPC_HOST", "ai-service")
AI_GRPC_PORT = int(os.environ.get("AI_GRPC_PORT", "50053"))

CORRELATION_WINDOW_MINUTES = int(os.environ.get("CORRELATION_WINDOW_MINUTES", "15"))
CORRELATION_WINDOW_SECONDS = CORRELATION_WINDOW_MINUTES * 60

CORS_ALLOW_ALL_ORIGINS = DEBUG

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

import structlog_setup

structlog_setup.configure_podiq_logging()
