import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402
from starlette.middleware.cors import (  # noqa: E402  # type: ignore[import-not-found]
    CORSMiddleware,
)
from strawberry.asgi import GraphQL  # noqa: E402

from app.graphql.schema import schema  # noqa: E402

_graphql_asgi = CORSMiddleware(
    GraphQL(schema),
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)
_django_asgi = get_asgi_application()


async def application(scope, receive, send):
    """
    Route /graphql (HTTP + WebSocket) to Strawberry ASGI so that the
    graphql-ws WebSocket subscription protocol works end-to-end.
    All other paths (healthz, REST, admin) go through Django.
    """
    if scope["path"] == "/graphql":
        await _graphql_asgi(scope, receive, send)
    else:
        await _django_asgi(scope, receive, send)
