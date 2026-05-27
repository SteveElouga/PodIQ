import datetime
from functools import partial

import strawberry
import structlog
from asgiref.sync import sync_to_async
from strawberry.types import Info

from app.auth import require_auth
from app.graphql.types import AnalysisHistoryItem
from app.grpc_clients import ai_client
from app.grpc_errors import GrpcService, invoke_grpc

logger = structlog.get_logger()


def _analysis_history(
    info: Info,
    pod_name: str,
    namespace: str,
    limit: int = 10,
    analysis_type: str = "",
) -> list[AnalysisHistoryItem]:
    ctx = require_auth(info)
    workspace_id = ctx.workspace_id or ""
    logger.info(
        "query_analysis_history",
        pod=pod_name,
        namespace=namespace,
        user_id=ctx.user_id,
        workspace_id=workspace_id,
    )

    response = invoke_grpc(
        GrpcService.AI,
        partial(
            ai_client.get_history,
            pod_name=pod_name,
            namespace=namespace,
            limit=limit,
            analysis_type=analysis_type,
            workspace_id=workspace_id,
        ),
    )

    return [
        AnalysisHistoryItem(
            id=item.id,
            pod_name=item.pod_name,
            namespace=item.namespace,
            error_type=item.error_type,
            root_cause=item.root_cause,
            solution=item.solution,
            confidence=item.confidence,
            is_recurring=item.is_recurring,
            recurrence_count=item.recurrence_count,
            created_at=datetime.datetime.fromtimestamp(item.created_at).isoformat(),
            analysis_type=item.analysis_type,
            risk_level=item.risk_level,
        )
        for item in response.items
    ]


@strawberry.field
async def analysis_history(
    info: Info, pod_name: str, namespace: str, limit: int = 10, analysis_type: str = ""
) -> list[AnalysisHistoryItem]:
    return await sync_to_async(_analysis_history)(
        info, pod_name, namespace, limit, analysis_type
    )
