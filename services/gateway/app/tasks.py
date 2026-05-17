"""Dramatiq async tasks for the gateway.

Broker selection:
  - Production: RedisBroker (REDIS_URL set in settings)
  - Tests: StubBroker (REDIS_URL="" in settings_pytest.py)
"""

import time
from functools import partial

import dramatiq
import structlog
from django.conf import settings

logger = structlog.get_logger()

# Configure broker at import time, once Django settings are ready.
_redis_url: str = getattr(settings, "REDIS_URL", "")
if _redis_url:
    from dramatiq.brokers.redis import RedisBroker as _RedisBroker

    dramatiq.set_broker(_RedisBroker(url=_redis_url))
else:
    from dramatiq.brokers.stub import StubBroker as _StubBroker

    dramatiq.set_broker(_StubBroker())


@dramatiq.actor(max_retries=2, time_limit=300_000)  # 5 min hard limit
def analyze_incident_task(
    job_id: str, user_id: str, pod_name: str, namespace: str
) -> None:
    """Run the full incident analysis pipeline and persist the result."""
    from app.grpc_clients import ai_client, analyzer_client
    from app.grpc_errors import GrpcService, invoke_grpc
    from app.namespace_correlation import build_namespace_context
    from core.models import AnalysisJob
    from stubs.ai import ai_pb2

    job = AnalysisJob.objects.get(id=job_id)
    job.status = AnalysisJob.Status.RUNNING
    job.save(update_fields=["status", "updated_at"])

    logger.info("task_analyze_start", job_id=job_id, pod=pod_name, namespace=namespace)

    try:
        pod_data = invoke_grpc(
            GrpcService.ANALYZER,
            partial(
                analyzer_client.collect_pod, pod_name=pod_name, namespace=namespace
            ),
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

        request = ai_pb2.IncidentRequest(
            pod_name=pod_data.pod_name,
            namespace=pod_data.namespace,
            status=pod_data.status,
            logs=pod_data.logs,
            events=pod_data.events,
            history=history,
            namespace_context=namespace_context,
        )

        result = invoke_grpc(
            GrpcService.AI, partial(ai_client.analyze_incident, request)
        )

        job.status = AnalysisJob.Status.COMPLETE
        job.result = {
            "error_type": result.error_type,
            "root_cause": result.root_cause,
            "explanation": result.explanation,
            "solution": result.solution,
            "confidence": result.confidence,
            "is_recurring": result.is_recurring,
            "recurrence_count": result.recurrence_count,
            "correlated_service": result.correlated_service or None,
            "correlation_explanation": result.correlation_explanation or None,
        }
        job.save(update_fields=["status", "result", "updated_at"])
        logger.info("task_analyze_complete", job_id=job_id, pod=pod_name)

    except Exception as exc:
        job.status = AnalysisJob.Status.FAILED
        job.error = str(exc)
        job.save(update_fields=["status", "error", "updated_at"])
        logger.error("task_analyze_failed", job_id=job_id, error=str(exc))
        raise
