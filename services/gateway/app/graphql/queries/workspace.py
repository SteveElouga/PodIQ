import strawberry
import structlog
from asgiref.sync import sync_to_async
from strawberry.types import Info

from app.auth import require_auth
from app.graphql.types import WorkspaceType
from core.models import WorkspaceMember

logger = structlog.get_logger()


def _list_workspaces(info: Info) -> list[WorkspaceType]:
    ctx = require_auth(info)
    memberships = (
        WorkspaceMember.objects.filter(user_id=ctx.user_id)
        .select_related("workspace")
        .order_by("workspace__created_at")
    )
    result = []
    for m in memberships:
        ws = m.workspace
        result.append(
            WorkspaceType(
                id=str(ws.id),
                name=ws.name,
                slug=ws.slug,
                plan=ws.plan,
                role=m.role,
                region=ws.region,
                team_size=ws.team_size,
                accent_color=ws.accent_color,
                onboarded_at=ws.onboarded_at.isoformat() if ws.onboarded_at else None,
                created_at=ws.created_at.isoformat(),
            )
        )
    return result


def _current_workspace(info: Info) -> WorkspaceType | None:
    ctx = require_auth(info)
    if not ctx.workspace_id:
        return None
    try:
        member = WorkspaceMember.objects.select_related("workspace").get(
            workspace_id=ctx.workspace_id, user_id=ctx.user_id
        )
    except WorkspaceMember.DoesNotExist:
        return None
    ws = member.workspace
    return WorkspaceType(
        id=str(ws.id),
        name=ws.name,
        slug=ws.slug,
        plan=ws.plan,
        role=member.role,
        region=ws.region,
        team_size=ws.team_size,
        accent_color=ws.accent_color,
        onboarded_at=ws.onboarded_at.isoformat() if ws.onboarded_at else None,
        created_at=ws.created_at.isoformat(),
    )


@strawberry.field
async def list_workspaces(info: Info) -> list[WorkspaceType]:
    return await sync_to_async(_list_workspaces)(info)


@strawberry.field
async def current_workspace(info: Info) -> WorkspaceType | None:
    return await sync_to_async(_current_workspace)(info)
