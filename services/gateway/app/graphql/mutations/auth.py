import re

import grpc
import strawberry
import structlog
from asgiref.sync import sync_to_async
from graphql import GraphQLError
from strawberry.types import Info

from app.api_codes import ErrorCode, graphql_error_extensions
from app.auth import require_auth
from app.graphql.types import ApiKeyPayload, AuthPayload
from app.grpc_clients import auth_client
from app.grpc_errors import GrpcService, raise_graphql_from_grpc

logger = structlog.get_logger()

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def _validate_email(email: str) -> None:
    if not _EMAIL_RE.match(email):
        raise GraphQLError(
            "Invalid email address",
            extensions=graphql_error_extensions(ErrorCode.VALIDATION),
        )


def _register(email: str, password: str) -> AuthPayload:
    _validate_email(email)
    logger.info("mutation_register", email=email)
    try:
        response = auth_client.register(email=email, password=password)
    except grpc.RpcError as exc:
        raise_graphql_from_grpc(exc, GrpcService.AUTH)
    return AuthPayload(
        token=response.token, user_id=response.user_id, email=response.email
    )


def _login(email: str, password: str) -> AuthPayload:
    _validate_email(email)
    logger.info("mutation_login", email=email)
    try:
        response = auth_client.login(email=email, password=password)
    except grpc.RpcError as exc:
        raise_graphql_from_grpc(exc, GrpcService.AUTH)
    return AuthPayload(
        token=response.token, user_id=response.user_id, email=response.email
    )


def _create_api_key(info: Info, name: str) -> ApiKeyPayload:
    ctx = require_auth(info)
    user_id = ctx.user_id
    logger.info("mutation_create_api_key", user_id=user_id, name=name)
    if not name.strip():
        raise GraphQLError(
            "API key name is required",
            extensions=graphql_error_extensions(ErrorCode.VALIDATION),
        )
    try:
        response = auth_client.create_api_key(user_id=user_id, name=name.strip())
    except grpc.RpcError as exc:
        raise_graphql_from_grpc(exc, GrpcService.AUTH)
    return ApiKeyPayload(
        key_id=response.key_id,
        raw_key=response.raw_key,
        name=response.name,
        created_at=response.created_at,
    )


def _revoke_api_key(info: Info, key_id: str) -> bool:
    ctx = require_auth(info)
    user_id = ctx.user_id
    logger.info("mutation_revoke_api_key", user_id=user_id, key_id=key_id)
    try:
        response = auth_client.revoke_api_key(key_id=key_id, user_id=user_id)
    except grpc.RpcError as exc:
        raise_graphql_from_grpc(exc, GrpcService.AUTH)
    return response.success


@strawberry.mutation
async def register(info: Info, email: str, password: str) -> AuthPayload:
    return await sync_to_async(_register)(email, password)


@strawberry.mutation
async def login(info: Info, email: str, password: str) -> AuthPayload:
    return await sync_to_async(_login)(email, password)


@strawberry.mutation
async def create_api_key(info: Info, name: str) -> ApiKeyPayload:
    return await sync_to_async(_create_api_key)(info, name)


@strawberry.mutation
async def revoke_api_key(info: Info, key_id: str) -> bool:
    return await sync_to_async(_revoke_api_key)(info, key_id)
