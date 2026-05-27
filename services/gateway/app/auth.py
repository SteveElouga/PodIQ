from dataclasses import dataclass

import grpc
import jwt as pyjwt
import structlog
from django.conf import settings
from graphql import GraphQLError
from strawberry.types import Info

from app.api_codes import ErrorCode, graphql_error_extensions
from app.grpc_clients import auth_client
from app.grpc_errors import GrpcService, raise_graphql_from_grpc

logger = structlog.get_logger()


@dataclass
class TokenContext:
    user_id: str
    email: str = ""
    workspace_id: str | None = None
    role: str | None = None


def _header_from_dict_ctx(ctx: dict) -> str:
    # WebSocket: token sent via connection_init payload (browsers can't set WS headers)
    params = ctx.get("connection_params") or {}
    if isinstance(params, dict):
        val = params.get("Authorization") or params.get("authorization") or ""
        if val:
            return val
    # HTTP: token in request headers
    req = ctx.get("request")
    if req is not None and hasattr(req, "headers"):
        return (
            req.headers.get("Authorization") or req.headers.get("authorization") or ""
        )
    return ""


def _extract_auth_header(info: Info) -> str:
    """Extract the Authorization header from any Strawberry context layout."""
    if not (info and info.context):
        return ""
    ctx = info.context
    if isinstance(ctx, dict):
        return _header_from_dict_ctx(ctx)
    if hasattr(ctx, "request") and hasattr(ctx.request, "headers"):
        return ctx.request.headers.get("Authorization", "")
    if hasattr(ctx, "headers"):
        return (
            ctx.headers.get("Authorization") or ctx.headers.get("authorization") or ""
        )
    return ""


def require_auth(info: Info) -> TokenContext:
    """Validate the JWT from the Authorization header.

    Workspace-JWT (signed by gateway with GATEWAY_JWT_SECRET): decoded locally — fast path.
    User-JWT (signed by auth-service): validated via gRPC — fallback path.

    Returns TokenContext. Raises PermissionError if missing/invalid.
    Raises GraphQLError if gRPC transport fails.
    """
    header = _extract_auth_header(info)

    if not header.startswith("Bearer "):
        raise GraphQLError(
            "Missing or invalid token format (expected: Bearer <token>)",
            extensions=graphql_error_extensions(ErrorCode.TOKEN_MISSING),
        )

    token = header.removeprefix("Bearer ").strip()
    if not token:
        raise GraphQLError(
            "Empty token",
            extensions=graphql_error_extensions(ErrorCode.TOKEN_MISSING),
        )

    # Fast path: workspace-JWT signed by gateway (GATEWAY_JWT_SECRET)
    gateway_secret = getattr(settings, "GATEWAY_JWT_SECRET", "")
    if gateway_secret:
        try:
            payload = pyjwt.decode(token, gateway_secret, algorithms=["HS256"])
            if "workspace_id" in payload:
                logger.debug("workspace_jwt_valid", user_id=payload.get("user_id"))
                return TokenContext(
                    user_id=payload["user_id"],
                    email=payload.get("email", ""),
                    workspace_id=payload["workspace_id"],
                    role=payload.get("role"),
                )
        except pyjwt.PyJWTError:
            pass  # not a gateway-signed workspace token — fall through to gRPC

    # Fallback: user-JWT validated via auth-service gRPC
    try:
        response = auth_client.validate_jwt(token)
    except grpc.RpcError as exc:
        raise_graphql_from_grpc(exc, GrpcService.AUTH)

    if not response.valid:
        logger.warning("jwt_invalid", error=response.error)
        raise GraphQLError(
            response.error or "Invalid or expired token",
            extensions=graphql_error_extensions(ErrorCode.TOKEN_INVALID),
        )

    logger.debug("jwt_valid", user_id=response.user_id)
    return TokenContext(user_id=response.user_id, email=getattr(response, "email", ""))
