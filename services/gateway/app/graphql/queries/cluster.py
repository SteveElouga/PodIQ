import strawberry
import structlog
from asgiref.sync import sync_to_async
from graphql import GraphQLError
from strawberry.types import Info

from app.api_codes import ErrorCode, graphql_error_extensions
from app.auth import require_auth
from app.graphql.types import ClusterType
from core.models import Cluster, WorkspaceMember

logger = structlog.get_logger()


def _cluster_status(info: Info, workspace_id: str) -> list[ClusterType]:
    ctx = require_auth(info)

    try:
        WorkspaceMember.objects.get(workspace_id=workspace_id, user_id=ctx.user_id)
    except WorkspaceMember.DoesNotExist:
        raise GraphQLError(
            "Access denied to workspace",
            extensions=graphql_error_extensions(ErrorCode.FORBIDDEN),
        )

    clusters = Cluster.objects.filter(workspace_id=workspace_id).order_by("created_at")

    return [
        ClusterType(
            id=str(c.id),
            name=c.name,
            k8s_version=c.k8s_version,
            status=c.status,
            workspace_id=str(c.workspace_id),
            last_heartbeat=(c.last_heartbeat.isoformat() if c.last_heartbeat else None),
            created_at=c.created_at.isoformat(),
        )
        for c in clusters
    ]


@strawberry.field
async def cluster_status(info: Info, workspace_id: str) -> list[ClusterType]:
    return await sync_to_async(_cluster_status)(info, workspace_id)
