from collections.abc import Callable
from enum import StrEnum
from typing import TypeVar

import grpc
import structlog
from graphql import GraphQLError

from app.api_codes import ErrorCode, graphql_error_extensions

logger = structlog.get_logger()

T = TypeVar("T")


class GrpcService(StrEnum):
    AUTH = "auth"
    ANALYZER = "analyzer"
    AI = "ai"


def _map_auth_status(status: grpc.StatusCode) -> ErrorCode:
    if status == grpc.StatusCode.ALREADY_EXISTS:
        return ErrorCode.CONFLICT
    if status == grpc.StatusCode.NOT_FOUND:
        return ErrorCode.NOT_FOUND
    if status == grpc.StatusCode.UNAUTHENTICATED:
        return ErrorCode.UNAUTHORIZED
    if status == grpc.StatusCode.INVALID_ARGUMENT:
        return ErrorCode.VALIDATION
    if status == grpc.StatusCode.DEADLINE_EXCEEDED:
        return ErrorCode.AUTH_GRPC
    if status == grpc.StatusCode.UNAVAILABLE:
        return ErrorCode.AUTH_GRPC
    return ErrorCode.AUTH_GRPC


def _map_analyzer_status(status: grpc.StatusCode) -> ErrorCode:
    if status == grpc.StatusCode.DEADLINE_EXCEEDED:
        return ErrorCode.ANALYZER_GRPC
    if status == grpc.StatusCode.UNAVAILABLE:
        return ErrorCode.K8S_UNAVAILABLE
    if status == grpc.StatusCode.NOT_FOUND:
        return ErrorCode.NOT_FOUND
    if status == grpc.StatusCode.INVALID_ARGUMENT:
        return ErrorCode.VALIDATION
    return ErrorCode.ANALYZER_GRPC


def _map_ai_status(status: grpc.StatusCode) -> ErrorCode:
    if status == grpc.StatusCode.DEADLINE_EXCEEDED:
        return ErrorCode.AI_TIMEOUT
    if status == grpc.StatusCode.UNAVAILABLE:
        return ErrorCode.AI_GRPC
    if status == grpc.StatusCode.NOT_FOUND:
        return ErrorCode.NOT_FOUND
    if status == grpc.StatusCode.INVALID_ARGUMENT:
        return ErrorCode.VALIDATION
    return ErrorCode.AI_GRPC


def _podiq_code(service: GrpcService, status: grpc.StatusCode) -> ErrorCode:
    if service == GrpcService.AUTH:
        return _map_auth_status(status)
    if service == GrpcService.ANALYZER:
        return _map_analyzer_status(status)
    return _map_ai_status(status)


def _default_message(service: GrpcService, status: grpc.StatusCode) -> str:
    if service == GrpcService.AUTH:
        return "Authentication service request failed"
    if service == GrpcService.ANALYZER:
        return "Analyzer service request failed"
    return "AI service request failed"


def raise_graphql_from_grpc(exc: grpc.RpcError, service: GrpcService) -> None:
    status = exc.code()
    podiq_code = _podiq_code(service, status)
    details = (exc.details() or "").strip()
    message = details if details else _default_message(service, status)
    logger.warning(
        "grpc_call_failed",
        service=service.value,
        grpc_status=status.name,
    )
    raise GraphQLError(
        message,
        extensions=graphql_error_extensions(podiq_code),
    ) from None


def invoke_grpc(service: GrpcService, fn: Callable[[], T]) -> T:
    try:
        return fn()
    except grpc.RpcError as exc:
        raise_graphql_from_grpc(exc, service)
