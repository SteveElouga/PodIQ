"""
analysisJob query tests.
Polls the AnalysisJob status from the gateway DB.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from graphql import GraphQLError

from app.auth import TokenContext

MOCK_USER_ID = "cafecafe-cafe-cafe-cafe-cafecafecafe"
MOCK_CTX = TokenContext(user_id=MOCK_USER_ID)
MOCK_JOB_ID = "ffffffff-eeee-dddd-cccc-bbbbbbbbbbbb"


def make_info() -> Any:
    return SimpleNamespace(
        context=SimpleNamespace(
            request=SimpleNamespace(headers={"Authorization": "Bearer tok"})
        )
    )


# ── analysisJob query ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestAnalysisJobQuery:
    def _run(self, job_id: str = MOCK_JOB_ID, user_id: str = MOCK_USER_ID) -> object:
        ctx = TokenContext(user_id=user_id)
        with patch("app.graphql.queries.job.require_auth", return_value=ctx):
            from app.graphql.queries.job import _analysis_job

            return _analysis_job(make_info(), job_id)

    def _create_job(
        self,
        status: str = "pending",
        result: dict | None = None,
        error: str = "",
    ) -> object:
        from core.models import AnalysisJob

        return AnalysisJob.objects.create(
            user_id=MOCK_USER_ID,
            pod_name="my-pod",
            namespace="default",
            status=status,
            result=result,
            error=error,
        )

    def test_pending_job_returns_pending_status(self):
        job = self._create_job(status="pending")
        result = self._run(job_id=str(job.id))
        assert result.status == "pending"
        assert result.result is None
        assert result.error is None

    def test_running_job_returns_running_status(self):
        job = self._create_job(status="running")
        result = self._run(job_id=str(job.id))
        assert result.status == "running"

    def test_complete_job_returns_result(self):
        analysis = {
            "error_type": "OOMKilled",
            "root_cause": "Memory exceeded",
            "explanation": "Container killed",
            "solution": "Add memory limits",
            "confidence": "high",
            "is_recurring": True,
            "recurrence_count": 3,
            "correlated_service": None,
            "correlation_explanation": None,
        }
        job = self._create_job(status="complete", result=analysis)
        result = self._run(job_id=str(job.id))
        assert result.status == "complete"
        assert result.result is not None
        assert result.result.error_type == "OOMKilled"
        assert result.result.root_cause == "Memory exceeded"
        assert result.result.is_recurring is True
        assert result.result.recurrence_count == 3

    def test_failed_job_returns_error(self):
        job = self._create_job(status="failed", error="gRPC connection refused")
        result = self._run(job_id=str(job.id))
        assert result.status == "failed"
        assert result.error == "gRPC connection refused"
        assert result.result is None

    def test_job_id_in_response(self):
        job = self._create_job()
        result = self._run(job_id=str(job.id))
        assert str(result.job_id) == str(job.id)

    def test_unknown_job_raises_graphql_error(self):
        from app.graphql.queries.job import _analysis_job

        with (
            patch("app.graphql.queries.job.require_auth", return_value=MOCK_CTX),
            pytest.raises(GraphQLError, match="Job not found"),
        ):
            _analysis_job(make_info(), "00000000-0000-0000-0000-000000000000")

    def test_wrong_user_cannot_read_job(self):
        job = self._create_job()
        from app.graphql.queries.job import _analysis_job

        other_user = "deadbeef-dead-beef-dead-beefdeadbeef"
        with (
            patch(
                "app.graphql.queries.job.require_auth",
                return_value=TokenContext(user_id=other_user),
            ),
            pytest.raises(GraphQLError, match="Job not found"),
        ):
            _analysis_job(make_info(), str(job.id))

    def test_invalid_uuid_raises_graphql_error(self):
        from app.graphql.queries.job import _analysis_job

        with (
            patch("app.graphql.queries.job.require_auth", return_value=MOCK_CTX),
            pytest.raises(GraphQLError, match="Job not found"),
        ):
            _analysis_job(make_info(), "not-a-uuid")

    def test_complete_job_correlated_service_is_set(self):
        analysis = {
            "error_type": "CrashLoopBackOff",
            "root_cause": "Dependency down",
            "explanation": "db-service crashed",
            "solution": "Restart db-service",
            "confidence": "medium",
            "is_recurring": False,
            "recurrence_count": 0,
            "correlated_service": "db-service",
            "correlation_explanation": "db-service crashed 2min before",
        }
        job = self._create_job(status="complete", result=analysis)
        result = self._run(job_id=str(job.id))
        assert result.result.correlated_service == "db-service"
        assert "2min" in result.result.correlation_explanation


class TestAnalysisJobAuth:
    def test_raises_permission_error_without_token(self):
        from app.graphql.queries.job import _analysis_job

        info = SimpleNamespace(
            context=SimpleNamespace(request=SimpleNamespace(headers={}))
        )
        with pytest.raises(PermissionError):
            _analysis_job(info, MOCK_JOB_ID)
