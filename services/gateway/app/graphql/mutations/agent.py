import strawberry
import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone as django_tz
from graphql import GraphQLError
from strawberry.types import Info

from app.graphql.types import AnalysisJobType, ClusterType
from app.tasks import analyze_incident_task
from core.models import AnalysisJob, Cluster, InstallToken

logger = structlog.get_logger()


def _resolve_install_token(raw_token: str) -> InstallToken:
    try:
        token = InstallToken.objects.select_related("workspace").get(token=raw_token)
    except InstallToken.DoesNotExist:
        raise GraphQLError("Invalid install token")

    # `used` means cluster registration complete — the agent keeps using the same
    # token for all subsequent heartbeats and incident reports, so we don't reject it.
    if token.expires_at < django_tz.now():
        raise GraphQLError("Install token expired")

    return token


def _agent_heartbeat(
    install_token: str, cluster_name: str, k8s_version: str = ""
) -> ClusterType:
    token = _resolve_install_token(install_token)
    workspace = token.workspace

    cluster, created = Cluster.objects.get_or_create(
        install_token=token,
        defaults={
            "workspace": workspace,
            "name": cluster_name,
            "k8s_version": k8s_version,
            "status": Cluster.Status.CONNECTED,
        },
    )

    if not created:
        cluster.status = Cluster.Status.CONNECTED
        cluster.k8s_version = k8s_version or cluster.k8s_version
        cluster.last_heartbeat = django_tz.now()
        cluster.save(update_fields=["status", "k8s_version", "last_heartbeat"])

    if created:
        token.used = True
        token.save(update_fields=["used"])

    logger.info(
        "agent_heartbeat",
        cluster_id=str(cluster.id),
        workspace_id=str(workspace.id),
        created=created,
    )

    return ClusterType(
        id=str(cluster.id),
        name=cluster.name,
        k8s_version=cluster.k8s_version,
        status=cluster.status,
        workspace_id=str(workspace.id),
        last_heartbeat=(
            cluster.last_heartbeat.isoformat() if cluster.last_heartbeat else None
        ),
        created_at=cluster.created_at.isoformat(),
    )


def _agent_report_incident(
    install_token: str,
    pod_name: str,
    namespace: str,
) -> AnalysisJobType:
    token = _resolve_install_token(install_token)
    workspace = token.workspace

    try:
        cluster = Cluster.objects.get(install_token=token)
    except Cluster.DoesNotExist:
        raise GraphQLError(
            "No cluster registered for this token — send heartbeat first"
        )

    job = AnalysisJob.objects.create(
        user_id=workspace.owner_id,
        workspace_id=workspace.id,
        pod_name=pod_name,
        namespace=namespace,
    )
    analyze_incident_task.send(
        str(job.id), str(workspace.owner_id), pod_name, namespace
    )

    logger.info(
        "agent_incident_reported",
        job_id=str(job.id),
        cluster_id=str(cluster.id),
        pod=pod_name,
        namespace=namespace,
    )

    return AnalysisJobType(
        job_id=strawberry.ID(str(job.id)),
        status=job.status,
        result=None,
        error=None,
        created_at=job.created_at.isoformat(),
    )


@strawberry.mutation
async def agent_heartbeat(
    info: Info,
    install_token: str,
    cluster_name: str,
    k8s_version: str = "",
) -> ClusterType:
    return await sync_to_async(_agent_heartbeat)(
        install_token, cluster_name, k8s_version
    )


@strawberry.mutation
async def agent_report_incident(
    info: Info,
    install_token: str,
    pod_name: str,
    namespace: str,
    logs: str = "",
    events: str = "",
    describe_output: str = "",
) -> AnalysisJobType:
    return await sync_to_async(_agent_report_incident)(
        install_token, pod_name, namespace
    )
