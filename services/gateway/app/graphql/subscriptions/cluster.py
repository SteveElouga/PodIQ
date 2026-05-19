import asyncio
from collections.abc import AsyncGenerator

import strawberry
import structlog
from asgiref.sync import sync_to_async
from strawberry.types import Info

from app.auth import require_auth
from app.graphql.types import ClusterType
from core.models import Cluster, WorkspaceMember

logger = structlog.get_logger()

_POLL_INTERVAL = 2  # seconds between DB polls


@strawberry.subscription
async def cluster_connected(
    info: Info, workspace_id: str
) -> AsyncGenerator[ClusterType, None]:
    """Stream until the first connected Cluster for the given workspace appears."""
    ctx = require_auth(info)
    if ctx.workspace_id != workspace_id:
        raise PermissionError("Access denied to workspace")

    member = await sync_to_async(
        lambda: WorkspaceMember.objects.filter(
            workspace_id=workspace_id, user_id=ctx.user_id
        ).first()
    )()
    if member is None:
        raise PermissionError("Not a member of this workspace")

    logger.info(
        "subscription_cluster_watching",
        workspace_id=workspace_id,
        user_id=ctx.user_id,
    )

    while True:
        cluster = await sync_to_async(
            lambda: Cluster.objects.filter(
                workspace_id=workspace_id, status=Cluster.Status.CONNECTED
            ).first()
        )()
        if cluster is not None:
            logger.info(
                "subscription_cluster_connected",
                cluster_id=str(cluster.id),
                workspace_id=workspace_id,
            )
            yield ClusterType(
                id=str(cluster.id),
                name=cluster.name,
                k8s_version=cluster.k8s_version,
                status=cluster.status,
                workspace_id=str(cluster.workspace_id),
                last_heartbeat=(
                    cluster.last_heartbeat.isoformat()
                    if cluster.last_heartbeat
                    else None
                ),
                created_at=cluster.created_at.isoformat(),
            )
            return
        await asyncio.sleep(_POLL_INTERVAL)
