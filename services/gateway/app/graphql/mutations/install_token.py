from datetime import timedelta

import strawberry
import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone as django_tz
from graphql import GraphQLError
from strawberry.types import Info

from app.api_codes import ErrorCode, graphql_error_extensions
from app.auth import require_auth
from app.graphql.types import InstallTokenPayload
from core.models import InstallToken, Workspace, WorkspaceMember

logger = structlog.get_logger()

_TOKEN_EXPIRY_HOURS = 24


def _generate_install_token(info: Info, workspace_id: str) -> InstallTokenPayload:
    ctx = require_auth(info)

    try:
        member = WorkspaceMember.objects.get(
            workspace_id=workspace_id, user_id=ctx.user_id
        )
    except WorkspaceMember.DoesNotExist:
        raise GraphQLError(
            "Access denied to workspace",
            extensions=graphql_error_extensions(ErrorCode.FORBIDDEN),
        )

    if member.role not in (WorkspaceMember.Role.ADMIN, WorkspaceMember.Role.MEMBER):
        raise GraphQLError(
            "At least Member role required to generate install tokens",
            extensions=graphql_error_extensions(ErrorCode.FORBIDDEN),
        )

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        raise GraphQLError(
            "Workspace not found",
            extensions=graphql_error_extensions(ErrorCode.NOT_FOUND),
        )

    expires_at = django_tz.now() + timedelta(hours=_TOKEN_EXPIRY_HOURS)
    token = InstallToken.objects.create(
        workspace=workspace,
        token=InstallToken.generate_token(),
        expires_at=expires_at,
    )

    logger.info(
        "install_token_generated",
        workspace_id=workspace_id,
        token_id=str(token.id),
        user_id=ctx.user_id,
    )

    return InstallTokenPayload(
        token=token.token,
        workspace_id=str(workspace.id),
        expires_at=expires_at.isoformat(),
    )


@strawberry.mutation
async def generate_install_token(info: Info, workspace_id: str) -> InstallTokenPayload:
    return await sync_to_async(_generate_install_token)(info, workspace_id)
