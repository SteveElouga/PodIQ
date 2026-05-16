import time
from functools import partial

import strawberry
import structlog
from django.conf import settings
from strawberry.types import Info

from app.graphql.types import AnalysisResultType
from app.grpc_clients import analyzer_client, ai_client
from app.auth import require_auth
from app.grpc_errors import GrpcService, invoke_grpc
from app.namespace_correlation import build_namespace_context
from stubs.ai import ai_pb2

logger = structlog.get_logger()


def _analyze_incident(info: Info, pod_name: str, namespace: str) -> AnalysisResultType:
    user_id = require_auth(info)
    logger.info("mutation_analyze_incident", pod=pod_name, namespace=namespace, user_id=user_id)

    pod_data = invoke_grpc(
        GrpcService.ANALYZER,
        partial(analyzer_client.collect_pod, pod_name=pod_name, namespace=namespace),
    )
    incident_ts = int(time.time())
    ns_snapshot = invoke_grpc(
        GrpcService.ANALYZER,
        partial(
            analyzer_client.scan_namespace,
            namespace=namespace,
            timestamp=incident_ts,
        ),
    )

    namespace_context = build_namespace_context(ns_snapshot, pod_data.pod_name)

    logger.info(
        "namespace_correlation_built",
        peer_pods=len(namespace_context),
        window_minutes=settings.CORRELATION_WINDOW_MINUTES,
    )

    history_response = invoke_grpc(
        GrpcService.AI,
        partial(
            ai_client.get_history,
            pod_name=pod_data.pod_name,
            namespace=pod_data.namespace,
            limit=5,
        ),
    )
    history = [
        ai_pb2.PastIncident(
            error_type=item.error_type,
            root_cause=item.root_cause,
            solution=item.solution,
            occurred_at=item.created_at,
        )
        for item in history_response.items
    ]

    logger.info(
        "memory_engine_history_loaded",
        pod=pod_data.pod_name,
        namespace=pod_data.namespace,
        history_count=len(history),
    )

    request = ai_pb2.IncidentRequest(
        pod_name=pod_data.pod_name,
        namespace=pod_data.namespace,
        status=pod_data.status,
        logs=pod_data.logs,
        events=pod_data.events,
        history=history,
        namespace_context=namespace_context,
    )

    result = invoke_grpc(GrpcService.AI, partial(ai_client.analyze_incident, request))

    return AnalysisResultType(
        error_type=result.error_type,
        root_cause=result.root_cause,
        explanation=result.explanation,
        solution=result.solution,
        confidence=result.confidence,
        is_recurring=result.is_recurring,
        recurrence_count=result.recurrence_count,
        correlated_service=result.correlated_service or None,
        correlation_explanation=result.correlation_explanation or None,
    )


@strawberry.mutation
def analyze_incident(info: Info, pod_name: str, namespace: str) -> AnalysisResultType:
    return _analyze_incident(info, pod_name, namespace)
