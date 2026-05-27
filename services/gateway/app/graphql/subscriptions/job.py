import asyncio
from collections.abc import AsyncGenerator

import strawberry
import structlog
from asgiref.sync import sync_to_async
from strawberry.types import Info

from app.auth import require_auth
from app.graphql.types import AnalysisJobType, AnalysisResultType
from core.models import AnalysisJob

logger = structlog.get_logger()

_POLL_INTERVAL = 3  # seconds between DB polls
_TERMINAL = {AnalysisJob.Status.COMPLETE, AnalysisJob.Status.FAILED}


def _job_to_type(job: AnalysisJob) -> AnalysisJobType:
    result: AnalysisResultType | None = None
    if job.status == AnalysisJob.Status.COMPLETE and job.result:
        r = job.result
        result = AnalysisResultType(
            error_type=r.get("error_type", ""),
            root_cause=r.get("root_cause", ""),
            explanation=r.get("explanation", ""),
            solution=r.get("solution", ""),
            confidence=r.get("confidence", ""),
            is_recurring=r.get("is_recurring", False),
            recurrence_count=r.get("recurrence_count", 0),
            correlated_service=r.get("correlated_service"),
            correlation_explanation=r.get("correlation_explanation"),
        )
    return AnalysisJobType(
        job_id=strawberry.ID(str(job.id)),
        status=job.status,
        result=result,
        error=job.error or None,
        created_at=job.created_at.isoformat(),
    )


@strawberry.subscription
async def job_status(info: Info, job_id: str) -> AsyncGenerator[AnalysisJobType, None]:
    """Stream AnalysisJob status updates until the job reaches a terminal state."""
    ctx = require_auth(info)

    # Prefer workspace-scoped access control; fall back to user_id for legacy JWTs.
    if ctx.workspace_id:
        get_job = sync_to_async(
            lambda: AnalysisJob.objects.filter(
                id=job_id, workspace_id=ctx.workspace_id
            ).first()
        )
    else:
        get_job = sync_to_async(
            lambda: AnalysisJob.objects.filter(id=job_id, user_id=ctx.user_id).first()
        )

    job = await get_job()
    if job is None:
        raise ValueError("Job not found or access denied")

    logger.info(
        "subscription_job_watching",
        job_id=job_id,
        user_id=ctx.user_id,
        workspace_id=ctx.workspace_id,
    )

    while True:
        job = await sync_to_async(lambda: AnalysisJob.objects.get(id=job_id))()
        yield _job_to_type(job)
        if job.status in _TERMINAL:
            return
        await asyncio.sleep(_POLL_INTERVAL)
