import strawberry
import structlog
from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from graphql import GraphQLError
from strawberry.types import Info

from app.api_codes import ErrorCode, graphql_error_extensions
from app.auth import require_auth
from app.graphql.types import AnalysisJobType, AnalysisResultType
from core.models import AnalysisJob

logger = structlog.get_logger()


def _analysis_job(info: Info, job_id: str) -> AnalysisJobType:
    ctx = require_auth(info)

    # Prefer workspace-scoped access control when a workspace-JWT is present.
    # Fall back to user_id for legacy user-JWT calls (no workspace context).
    try:
        if ctx.workspace_id:
            job = AnalysisJob.objects.get(id=job_id, workspace_id=ctx.workspace_id)
        else:
            job = AnalysisJob.objects.get(id=job_id, user_id=ctx.user_id)
    except (AnalysisJob.DoesNotExist, ValueError, ValidationError):
        raise GraphQLError(
            "Job not found",
            extensions=graphql_error_extensions(ErrorCode.NOT_FOUND),
        )

    logger.debug("query_analysis_job", job_id=job_id, status=job.status)

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


@strawberry.field
async def analysis_job(info: Info, job_id: str) -> AnalysisJobType:
    return await sync_to_async(_analysis_job)(info, job_id)
