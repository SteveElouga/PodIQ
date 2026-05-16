"""Codes machine-lisibles (PodIQ).

Convention GraphQL (recommandée)
--------------------------------
- Succès : ``data`` renseigné et pas d’entrée dans ``errors``. Pas besoin d’un
  code de succès dans le corps : c’est le contrat GraphQL standard.
- Échec : levée d’une erreur GraphQL (ex. Strawberry ``GraphQLError``) avec
  ``extensions`` contenant au minimum la clé définie par ``GRAPHQL_EXTENSION_CODE``
  et la valeur = un membre de ``ErrorCode`` (chaîne ``PODIQ_*``).
- Ne pas s’appuyer sur le statut HTTP pour la logique métier : le playground et
  beaucoup de clients reçoivent souvent **200** avec ``errors`` non vide.
- Le mapping HTTP ci-dessous sert surtout pour une future couche REST / CI/CD ;
  pour du GraphQL pur, il est optionnel et non prioritaire.

Messages utilisateur : texte lisible dans ``message`` ; codes stables dans
``extensions`` pour i18n, analytics et clients programmatiques.
"""

from enum import StrEnum
from typing import Any, Final

HTTP_OK: Final[int] = 200

GRAPHQL_EXTENSION_CODE: Final[str] = "code"


class SuccessCode(StrEnum):
    OK = "PODIQ_OK"

    REGISTERED = "PODIQ_AUTH_REGISTERED"
    LOGGED_IN = "PODIQ_AUTH_LOGGED_IN"

    INCIDENT_ANALYZED = "PODIQ_INCIDENT_ANALYZED"
    MANIFEST_SCANNED = "PODIQ_MANIFEST_SCANNED"
    HISTORY_RETURNED = "PODIQ_HISTORY_RETURNED"


class ErrorCode(StrEnum):
    VALIDATION = "PODIQ_VALIDATION_ERROR"

    UNAUTHORIZED = "PODIQ_UNAUTHORIZED"
    TOKEN_MISSING = "PODIQ_TOKEN_MISSING"
    TOKEN_INVALID = "PODIQ_TOKEN_INVALID"

    FORBIDDEN = "PODIQ_FORBIDDEN"

    PAYMENT_OR_PLAN_REQUIRED = "PODIQ_PAYMENT_OR_PLAN_REQUIRED"

    AUTH_GRPC = "PODIQ_AUTH_GRPC_ERROR"
    ANALYZER_GRPC = "PODIQ_ANALYZER_GRPC_ERROR"
    AI_GRPC = "PODIQ_AI_GRPC_ERROR"

    AI_PARSE = "PODIQ_AI_RESPONSE_PARSE_ERROR"
    AI_TIMEOUT = "PODIQ_AI_TIMEOUT"
    K8S_UNAVAILABLE = "PODIQ_K8S_UNAVAILABLE"

    NOT_FOUND = "PODIQ_NOT_FOUND"
    CONFLICT = "PODIQ_CONFLICT"

    INTERNAL = "PODIQ_INTERNAL_ERROR"


ERROR_HTTP_STATUS: Final[dict[ErrorCode, int]] = {
    ErrorCode.VALIDATION: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.TOKEN_MISSING: 401,
    ErrorCode.TOKEN_INVALID: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.PAYMENT_OR_PLAN_REQUIRED: 402,
    ErrorCode.AUTH_GRPC: 502,
    ErrorCode.ANALYZER_GRPC: 502,
    ErrorCode.AI_GRPC: 502,
    ErrorCode.AI_PARSE: 502,
    ErrorCode.AI_TIMEOUT: 504,
    ErrorCode.K8S_UNAVAILABLE: 503,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INTERNAL: 500,
}


def http_status_for_error(code: ErrorCode) -> int:
    return ERROR_HTTP_STATUS[code]


def graphql_error_extensions(code: ErrorCode, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {GRAPHQL_EXTENSION_CODE: code.value}
    base.update(extra)
    return base
