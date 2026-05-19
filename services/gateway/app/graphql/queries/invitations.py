import strawberry
import structlog
from asgiref.sync import sync_to_async
from strawberry.types import Info

from app.auth import require_auth
from app.graphql.mutations.invitation import InvitationPayload
from core.models import Invitation, WorkspaceMember

logger = structlog.get_logger()


def _list_invitations(
    info: Info, workspace_id: str, status: str = ""
) -> list[InvitationPayload]:
    ctx = require_auth(info)

    try:
        WorkspaceMember.objects.get(
            workspace_id=workspace_id,
            user_id=ctx.user_id,
            role=WorkspaceMember.Role.ADMIN,
        )
    except WorkspaceMember.DoesNotExist:
        raise PermissionError("Admin access required")

    qs = Invitation.objects.filter(workspace_id=workspace_id)
    if status:
        qs = qs.filter(status=status)

    return [
        InvitationPayload(
            id=str(inv.id),
            token=str(inv.token),
            email=inv.email,
            role=inv.role,
            status=inv.status,
            expires_at=inv.expires_at.isoformat(),
            created_at=inv.created_at.isoformat(),
        )
        for inv in qs.order_by("-created_at")
    ]


@strawberry.field
async def list_invitations(
    info: Info, workspace_id: str, status: str = ""
) -> list[InvitationPayload]:
    return await sync_to_async(_list_invitations)(info, workspace_id, status)
