import grpc
import structlog
from strawberry.types import Info

from app.grpc_clients import auth_client
from app.grpc_errors import GrpcService, raise_graphql_from_grpc

logger = structlog.get_logger()


def require_auth(info: Info) -> str:
    """Valide le JWT fourni dans le header Authorization.

    Appelle auth-service via gRPC (ValidateJWT).
    Retourne le user_id si le token est valide.
    Raises PermissionError if missing, malformed, or invalid JWT payload.
    Raises GraphQLError if the auth-service gRPC call fails (transport / service error).
    """
    header: str = ""
    if info and info.context and hasattr(info.context, "request"):
        header = info.context.request.headers.get("Authorization", "")

    if not header.startswith("Bearer "):
        raise PermissionError(
            "Missing or invalid Authorization header (expected: Bearer <token>)"
        )

    token = header.removeprefix("Bearer ").strip()
    if not token:
        raise PermissionError("Empty token")

    try:
        response = auth_client.validate_jwt(token)
    except grpc.RpcError as exc:
        raise_graphql_from_grpc(exc, GrpcService.AUTH)

    if not response.valid:
        logger.warning("jwt_invalid", error=response.error)
        raise PermissionError(response.error or "Invalid or expired token")

    logger.debug("jwt_valid", user_id=response.user_id)
    return response.user_id
