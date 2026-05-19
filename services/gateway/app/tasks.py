"""Dramatiq async tasks for the gateway.

Broker selection:
  - Production: RedisBroker (REDIS_URL set in settings)
  - Tests: StubBroker (REDIS_URL="" in settings_pytest.py)
"""

import datetime
import time
from functools import partial
from typing import TYPE_CHECKING

import dramatiq
import structlog
from django.conf import settings

if TYPE_CHECKING:
    from core.models import NotificationChannel, QuietHours

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
    job.error = ""
    job.save(update_fields=["status", "error", "updated_at"])

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
        logger.info(
            "task_analyze_complete",
            job_id=job_id,
            pod=pod_name,
            is_recurring=result.is_recurring,
        )

        # Trigger notifications if workspace is known
        if job.workspace_id:
            event = "crashloop" if "crash" in result.error_type.lower() else "fix_found"
            send_notifications_task.send(
                str(job.workspace_id),
                event,
                {
                    "job_id": job_id,
                    "pod_name": pod_name,
                    "namespace": namespace,
                    "error_type": result.error_type,
                    "solution": result.solution,
                },
            )

    except Exception as exc:
        job.status = AnalysisJob.Status.FAILED
        job.error = str(exc)
        job.save(update_fields=["status", "error", "updated_at"])
        logger.error("task_analyze_failed", job_id=job_id, error=str(exc))
        raise


@dramatiq.actor(max_retries=1, time_limit=60_000)
def send_notifications_task(workspace_id: str, event_type: str, context: dict) -> None:
    """Dispatch notifications to all enabled channels for the workspace+event."""
    from core.models import AlertRule, NotificationChannel, QuietHours

    rules = list(
        AlertRule.objects.filter(
            workspace_id=workspace_id, event_type=event_type, enabled=True
        )
    )
    if not rules:
        return

    try:
        qh = QuietHours.objects.get(workspace_id=workspace_id, enabled=True)
        if _is_quiet_period(qh) and event_type != "crashloop":
            logger.info(
                "notifications_suppressed_quiet_hours",
                workspace_id=workspace_id,
                event_type=event_type,
            )
            return
    except QuietHours.DoesNotExist:
        pass

    channels = list(
        NotificationChannel.objects.filter(workspace_id=workspace_id, enabled=True)
    )
    for channel in channels:
        try:
            _dispatch_channel(channel, event_type, context)
        except Exception as exc:
            logger.error(
                "notification_dispatch_failed",
                channel_id=str(channel.id),
                channel_type=channel.type,
                error=str(exc),
            )

    logger.info(
        "notifications_sent",
        workspace_id=workspace_id,
        event_type=event_type,
        channels_count=len(channels),
    )


def _is_quiet_period(qh: "QuietHours") -> bool:
    import zoneinfo

    try:
        tz: datetime.tzinfo = zoneinfo.ZoneInfo(qh.timezone)
    except Exception:
        tz = datetime.UTC

    now = datetime.datetime.now(tz)
    if qh.weekdays_only and now.weekday() >= 5:
        return False

    current_time = now.time().replace(tzinfo=None)
    start = qh.start_time
    end = qh.end_time

    if start <= end:
        return start <= current_time <= end
    # overnight range (e.g. 22:00 – 06:00)
    return current_time >= start or current_time <= end


def _dispatch_channel(
    channel: "NotificationChannel", event_type: str, context: dict
) -> None:
    import httpx

    from core.models import NotificationChannel as NC

    cfg = channel.config
    message = (
        f"[PodIQ] {event_type.upper()} — "
        f"{context.get('pod_name', '?')} in {context.get('namespace', '?')}\n"
        f"Error: {context.get('error_type', '')}\n"
        f"Fix: {context.get('solution', '')}"
    )

    if channel.type in (
        NC.ChannelType.SLACK,
        NC.ChannelType.DISCORD,
        NC.ChannelType.TEAMS,
    ):
        webhook_url = cfg.get("webhook_url", "")
        if not webhook_url:
            return
        httpx.post(webhook_url, json={"text": message}, timeout=10)

    elif channel.type == NC.ChannelType.WEBHOOK:
        url = cfg.get("url", "")
        if not url:
            return
        httpx.post(url, json={"event": event_type, "context": context}, timeout=10)

    elif channel.type == NC.ChannelType.PAGERDUTY:
        routing_key = cfg.get("routing_key", "")
        if not routing_key:
            return
        httpx.post(
            "https://events.pagerduty.com/v2/enqueue",
            json={
                "routing_key": routing_key,
                "event_action": "trigger",
                "payload": {
                    "summary": message,
                    "severity": "critical" if event_type == "crashloop" else "warning",
                    "source": "podiq",
                },
            },
            timeout=10,
        )

    elif channel.type == NC.ChannelType.EMAIL:
        address = cfg.get("address", "")
        if not address:
            return
        _send_email(address, f"[PodIQ] {event_type}", message)


def _send_email(to: str, subject: str, body: str) -> None:
    import smtplib
    from email.mime.text import MIMEText

    from django.conf import settings

    smtp_host = getattr(settings, "SMTP_HOST", "")
    smtp_port = int(getattr(settings, "SMTP_PORT", 587))
    smtp_user = getattr(settings, "SMTP_USER", "")
    smtp_password = getattr(settings, "SMTP_PASSWORD", "")

    if not smtp_host:
        logger.warning("smtp_not_configured", to=to)
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        if smtp_user:
            server.login(smtp_user, smtp_password)
        server.send_message(msg)
