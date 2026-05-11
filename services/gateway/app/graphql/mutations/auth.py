import strawberry
import structlog
from strawberry.types import Info

from app.graphql.types import AuthPayload
from app.grpc_clients import auth_client

logger = structlog.get_logger()


def _register(info: Info, email: str, password: str) -> AuthPayload:
    logger.info("mutation_register", email=email)
    response = auth_client.register(email=email, password=password)
    return AuthPayload(token=response.token, user_id=response.user_id, email=response.email)


def _login(info: Info, email: str, password: str) -> AuthPayload:
    logger.info("mutation_login", email=email)
    response = auth_client.login(email=email, password=password)
    return AuthPayload(token=response.token, user_id=response.user_id, email=response.email)


@strawberry.mutation
def register(info: Info, email: str, password: str) -> AuthPayload:
    return _register(info, email, password)


@strawberry.mutation
def login(info: Info, email: str, password: str) -> AuthPayload:
    return _login(info, email, password)
