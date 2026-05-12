import grpc
import structlog
from strawberry.types import Info

from app.grpc_clients import auth_client
from app.grpc_errors import GrpcService, raise_graphql_from_grpc

logger = structlog.get_logger()


def _register(info: Info, email: str, password: str) -> AuthPayload:
    logger.info("mutation_register", email=email)
    try:
        response = auth_client.register(email=email, password=password)
    except grpc.RpcError as exc:
        raise_graphql_from_grpc(exc, GrpcService.AUTH)
    return AuthPayload(token=response.token, user_id=response.user_id, email=response.email)


def _login(info: Info, email: str, password: str) -> AuthPayload:
    logger.info("mutation_login", email=email)
    try:
        response = auth_client.login(email=email, password=password)
    except grpc.RpcError as exc:
        raise_graphql_from_grpc(exc, GrpcService.AUTH)
    return AuthPayload(token=response.token, user_id=response.user_id, email=response.email)


@strawberry.mutation
def register(info: Info, email: str, password: str) -> AuthPayload:
    return _register(info, email, password)


@strawberry.mutation
def login(info: Info, email: str, password: str) -> AuthPayload:
    return _login(info, email, password)
