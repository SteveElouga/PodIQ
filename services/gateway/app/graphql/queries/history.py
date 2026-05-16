import datetime
from functools import partial

import strawberry
import structlog
from strawberry.types import Info

from app.graphql.types import AnalysisHistoryItem
from app.grpc_clients import ai_client
from app.auth import require_auth
from app.grpc_errors import GrpcService, invoke_grpc

logger = structlog.get_logger()


def _analysis_history(
    info: Info,
    pod_name: str,
    namespace: str,
    limit: int = 10,
) -> list[AnalysisHistoryItem]:
    user_id = require_auth(info)
    logger.info("query_analysis_history", pod=pod_name, namespace=namespace, user_id=user_id)

    response = invoke_grpc(
        GrpcService.AI,
        partial(
            ai_client.get_history,
            pod_name=pod_name,
            namespace=namespace,
            limit=limit,
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
        )
        for item in response.items
    ]


@strawberry.field
def analysis_history(info: Info, pod_name: str, namespace: str, limit: int = 10) -> list[AnalysisHistoryItem]:
    return _analysis_history(info, pod_name, namespace, limit)
