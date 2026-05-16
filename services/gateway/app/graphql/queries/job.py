import strawberry
import structlog
from django.core.exceptions import ValidationError
from graphql import GraphQLError
from strawberry.types import Info

from app.auth import require_auth
from app.graphql.types import AnalysisJobType, AnalysisResultType
from core.models import AnalysisJob

logger = structlog.get_logger()


def _analysis_job(info: Info, job_id: str) -> AnalysisJobType:
    user_id = require_auth(info)

    try:
        job = AnalysisJob.objects.get(id=job_id, user_id=user_id)
    except (AnalysisJob.DoesNotExist, ValueError, ValidationError):
        raise GraphQLError("Job not found")

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
def analysis_job(info: Info, job_id: str) -> AnalysisJobType:
    return _analysis_job(info, job_id)
