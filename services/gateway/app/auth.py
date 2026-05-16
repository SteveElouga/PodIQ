import structlog
from strawberry.types import Info

from app.grpc_clients import auth_client

logger = structlog.get_logger()


def require_auth(info: Info) -> str:
    """Valide le JWT fourni dans le header Authorization.

    Appelle auth-service via gRPC (ValidateJWT).
    Retourne le user_id si le token est valide.
    Lève PermissionError si absent, mal formé ou invalide.
    """
    header: str = ""
    if info and info.context and hasattr(info.context, "request"):
        header = info.context.request.headers.get("Authorization", "")

    if not header.startswith("Bearer "):
        raise PermissionError("Token manquant ou format invalide (attendu : Bearer <token>)")

    token = header.removeprefix("Bearer ").strip()
    if not token:
        raise PermissionError("Token vide")

    response = auth_client.validate_jwt(token)

    if not response.valid:
        logger.warning("jwt_invalid", error=response.error)
        raise PermissionError(response.error or "Token invalide ou expiré")

    logger.debug("jwt_valid", user_id=response.user_id)
    return response.user_id
