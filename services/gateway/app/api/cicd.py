"""CI/CD REST endpoint — POST /api/v1/cicd/scan.

Authenticates via X-Api-Key header (auth-service ValidateApiKey),
parses and scans a YAML manifest, returns a machine-readable JSON body
with an exit_code for pipeline gate integration:
  0 — safe      (deploy allowed)
  1 — warning   (deploy allowed, review recommended)
  2 — block     (deploy blocked)
"""

import json
from functools import partial
from typing import Any

import grpc
import structlog
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from app.api_codes import ErrorCode
from app.grpc_clients import ai_client, analyzer_client, auth_client
from app.grpc_errors import GrpcService

logger = structlog.get_logger()

_RISK_TO_EXIT: dict[str, int] = {
    "safe": 0,
    "warning": 1,
    "block": 2,
}


def _error(message: str, code: ErrorCode, status: int) -> JsonResponse:
    return JsonResponse({"error": message, "code": code.value}, status=status)


def _invoke(
    service: GrpcService, fn: partial  # type: ignore[type-arg]
) -> tuple[Any, JsonResponse | None]:
    """Call a gRPC function; return (result, None) on success or (None, error response)."""
    try:
        return fn(), None
    except grpc.RpcError as exc:
        grpc_status = exc.code()
        details = (exc.details() or "").strip()
        logger.warning(
            "grpc_call_failed",
            service=service.value,
            grpc_status=grpc_status.name,
        )
        if grpc_status == grpc.StatusCode.INVALID_ARGUMENT:
            return None, _error(details or "Invalid input", ErrorCode.VALIDATION, 400)
        if grpc_status in (
            grpc.StatusCode.UNAVAILABLE,
            grpc.StatusCode.DEADLINE_EXCEEDED,
        ):
            if service == GrpcService.AUTH:
                return None, _error(
                    "Authentication service unavailable", ErrorCode.AUTH_GRPC, 502
                )
            if service == GrpcService.ANALYZER:
                return None, _error(
                    "Analyzer service unavailable", ErrorCode.ANALYZER_GRPC, 502
                )
            return None, _error("AI service unavailable", ErrorCode.AI_GRPC, 502)
        if service == GrpcService.AUTH:
            return None, _error(
                "Authentication service error", ErrorCode.AUTH_GRPC, 502
            )
        if service == GrpcService.ANALYZER:
            return None, _error("Analyzer service error", ErrorCode.ANALYZER_GRPC, 502)
        return None, _error("AI service error", ErrorCode.AI_GRPC, 502)


@csrf_exempt
@require_POST
def scan(request: HttpRequest) -> JsonResponse:
    """POST /api/v1/cicd/scan

    Headers:
        X-Api-Key: <raw api key>
        Content-Type: application/json

    Body:
        {"yaml_content": "<manifest yaml>", "manifest_type": ""}  (manifest_type optional)

    Response 200:
        {"exit_code": 0|1|2, "risk_level": "safe|warning|block",
         "summary": "...", "risks": [...]}

    Exit codes: 0=safe, 1=warning, 2=block
    """
    raw_key = request.headers.get("X-Api-Key", "").strip()
    if not raw_key:
        return _error("Missing X-Api-Key header", ErrorCode.TOKEN_MISSING, 401)

    auth_result, err = _invoke(
        GrpcService.AUTH,
        partial(auth_client.validate_api_key, raw_key=raw_key),
    )
    if err:
        return err
    if not auth_result.valid:
        logger.warning("cicd_api_key_invalid", error=auth_result.error)
        return _error("Invalid or revoked API key", ErrorCode.TOKEN_INVALID, 401)

    user_id = auth_result.user_id
    logger.info("cicd_scan_start", user_id=user_id)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error("Request body must be valid JSON", ErrorCode.VALIDATION, 400)

    yaml_content: str = body.get("yaml_content", "").strip()
    manifest_type: str = body.get("manifest_type", "")

    if not yaml_content:
        return _error("yaml_content is required", ErrorCode.VALIDATION, 400)

    parsed, err = _invoke(
        GrpcService.ANALYZER,
        partial(
            analyzer_client.parse_manifest,
            yaml_content=yaml_content,
            manifest_type=manifest_type,
        ),
    )
    if err:
        return err

    result, err = _invoke(
        GrpcService.AI,
        partial(
            ai_client.scan_manifest,
            parsed_manifest=parsed.raw_config,
            related_history=[],
        ),
    )
    if err:
        return err

    risk_level = result.risk_level or "safe"
    exit_code = _RISK_TO_EXIT.get(risk_level, 2)

    logger.info(
        "cicd_scan_complete",
        user_id=user_id,
        risk_level=risk_level,
        exit_code=exit_code,
        risk_count=len(result.risks),
    )

    return JsonResponse(
        {
            "exit_code": exit_code,
            "risk_level": risk_level,
            "summary": result.summary,
            "risks": [
                {
                    "severity": r.severity,
                    "category": r.category,
                    "description": r.description,
                    "fix": r.fix,
                }
                for r in result.risks
            ],
        }
    )
