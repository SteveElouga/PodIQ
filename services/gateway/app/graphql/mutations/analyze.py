import strawberry
import structlog
from asgiref.sync import sync_to_async
from strawberry.types import Info

from app.auth import require_auth
from app.graphql.types import AnalysisJobType
from app.tasks import analyze_incident_task
from core.models import AnalysisJob

logger = structlog.get_logger()


def _analyze_incident(info: Info, pod_name: str, namespace: str) -> AnalysisJobType:
    ctx = require_auth(info)
    user_id = ctx.user_id
    logger.info(
        "mutation_analyze_incident", pod=pod_name, namespace=namespace, user_id=user_id
    )

    job = AnalysisJob.objects.create(
        user_id=user_id,
        workspace_id=ctx.workspace_id,
        pod_name=pod_name,
        namespace=namespace,
    )

    analyze_incident_task.send(str(job.id), user_id, pod_name, namespace)

    logger.info("task_enqueued", job_id=str(job.id), pod=pod_name, namespace=namespace)

    return AnalysisJobType(
        job_id=strawberry.ID(str(job.id)),
        status=job.status,
        result=None,
        error=None,
        created_at=job.created_at.isoformat(),
    )


@strawberry.mutation
async def analyze_incident(
    info: Info, pod_name: str, namespace: str
) -> AnalysisJobType:
    return await sync_to_async(_analyze_incident)(info, pod_name, namespace)
