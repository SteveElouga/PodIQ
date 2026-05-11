import time

import strawberry
import structlog
from strawberry.types import Info

from app.graphql.types import AnalysisResultType
from app.grpc_clients import analyzer_client, ai_client
from stubs.ai import ai_pb2

logger = structlog.get_logger()


def _analyze_incident(info: Info, pod_name: str, namespace: str) -> AnalysisResultType:
    logger.info("mutation_analyze_incident", pod=pod_name, namespace=namespace)

    pod_data = analyzer_client.collect_pod(pod_name=pod_name, namespace=namespace)
    ns_snapshot = analyzer_client.scan_namespace(
        namespace=namespace,
        timestamp=int(time.time()),
    )

    namespace_context = [
        ai_pb2.PodContext(
            pod_name=p.pod_name,
            status=p.status,
            had_issues=p.has_errors,
            issue_timestamp=p.last_restart_time,
        )
        for p in ns_snapshot.pods
        if p.pod_name != pod_name
    ]

    history_response = ai_client.get_history(
        pod_name=pod_data.pod_name,
        namespace=pod_data.namespace,
        limit=5,
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

    result = ai_client.analyze_incident(request)

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
