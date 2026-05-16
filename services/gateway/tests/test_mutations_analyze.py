"""
analyzeIncident mutation tests.
Mutation now enqueues a Dramatiq task and returns a job_id immediately.
gRPC clients and Dramatiq actor are fully mocked.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

MOCK_USER_ID = "user-uuid-test"
MOCK_JOB_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def make_info(token: str | None = "Bearer test-token") -> Any:
    headers: dict = {}
    if token:
        headers["Authorization"] = token
    return SimpleNamespace(
        context=SimpleNamespace(request=SimpleNamespace(headers=headers))
    )


def make_job(
    job_id: str = MOCK_JOB_ID,
    status: str = "pending",
    result: dict | None = None,
    error: str = "",
) -> MagicMock:
    job = MagicMock()
    job.id = job_id
    job.status = status
    job.result = result
    job.error = error
    job.created_at.isoformat.return_value = "2026-05-16T12:00:00"
    return job


# ── analyzeIncident mutation ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestAnalyzeIncidentMutation:
    def _run(self, job: MagicMock | None = None, user_id: str = MOCK_USER_ID) -> dict:
        job = job or make_job()
        with (
            patch("app.graphql.mutations.analyze.require_auth", return_value=user_id),
            patch(
                "app.graphql.mutations.analyze.AnalysisJob.objects.create",
                return_value=job,
            ),
            patch(
                "app.graphql.mutations.analyze.analyze_incident_task.send"
            ) as mock_send,
        ):
            from app.graphql.mutations.analyze import _analyze_incident

            result = _analyze_incident(make_info(), "crashloop-pod", "default")
            return {"result": result, "send": mock_send}

    def test_returns_job_id(self):
        data = self._run()
        assert str(data["result"].job_id) == MOCK_JOB_ID

    def test_returns_pending_status(self):
        data = self._run()
        assert data["result"].status == "pending"

    def test_result_is_none_while_pending(self):
        data = self._run()
        assert data["result"].result is None

    def test_error_is_none_while_pending(self):
        data = self._run()
        assert data["result"].error is None

    def test_returns_created_at(self):
        data = self._run()
        assert data["result"].created_at == "2026-05-16T12:00:00"

    def test_task_is_sent_with_correct_args(self):
        job = make_job(job_id=MOCK_JOB_ID)
        data = self._run(job=job)
        data["send"].assert_called_once_with(
            MOCK_JOB_ID, MOCK_USER_ID, "crashloop-pod", "default"
        )

    def test_job_created_with_user_pod_namespace(self):
        with (
            patch(
                "app.graphql.mutations.analyze.require_auth", return_value=MOCK_USER_ID
            ),
            patch(
                "app.graphql.mutations.analyze.AnalysisJob.objects.create",
                return_value=make_job(),
            ) as mock_create,
            patch("app.graphql.mutations.analyze.analyze_incident_task.send"),
        ):
            from app.graphql.mutations.analyze import _analyze_incident

            _analyze_incident(make_info(), "my-pod", "staging")

        mock_create.assert_called_once_with(
            user_id=MOCK_USER_ID,
            pod_name="my-pod",
            namespace="staging",
        )


class TestAnalyzeIncidentAuth:
    def test_raises_permission_error_without_token(self):
        from app.graphql.mutations.analyze import _analyze_incident

        with pytest.raises(PermissionError):
            _analyze_incident(make_info(token=None), "pod", "ns")


# ── Dramatiq task ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestAnalyzeIncidentTask:
    def _make_grpc_results(self) -> tuple:
        pod_data = SimpleNamespace(
            pod_name="crashloop-pod",
            namespace="default",
            status="CrashLoopBackOff",
            logs="OOMKilled",
            events="BackOff",
        )
        ns_snapshot = SimpleNamespace(pods=[], collected_at=0)
        history_response = SimpleNamespace(items=[])
        ai_result = SimpleNamespace(
            error_type="OOMKilled",
            root_cause="Memory limit too low",
            explanation="Container exceeded memory limit",
            solution="Increase memory limit",
            confidence="high",
            is_recurring=False,
            recurrence_count=0,
            correlated_service="",
            correlation_explanation="",
        )
        return pod_data, ns_snapshot, history_response, ai_result

    def test_task_marks_job_complete(self):
        from core.models import AnalysisJob

        job = AnalysisJob.objects.create(
            user_id="11111111-1111-1111-1111-111111111111",
            pod_name="crashloop-pod",
            namespace="default",
        )
        pod_data, ns_snapshot, history_response, ai_result = self._make_grpc_results()

        with (
            patch(
                "app.grpc_clients.analyzer_client.collect_pod", return_value=pod_data
            ),
            patch(
                "app.grpc_clients.analyzer_client.scan_namespace",
                return_value=ns_snapshot,
            ),
            patch(
                "app.grpc_clients.ai_client.get_history", return_value=history_response
            ),
            patch(
                "app.grpc_clients.ai_client.analyze_incident", return_value=ai_result
            ),
        ):
            from app.tasks import analyze_incident_task

            analyze_incident_task(
                str(job.id), str(job.user_id), job.pod_name, job.namespace
            )

        job.refresh_from_db()
        assert job.status == AnalysisJob.Status.COMPLETE
        assert job.result["error_type"] == "OOMKilled"
        assert job.result["root_cause"] == "Memory limit too low"

    def test_task_stores_full_result_fields(self):
        from core.models import AnalysisJob

        job = AnalysisJob.objects.create(
            user_id="22222222-2222-2222-2222-222222222222",
            pod_name="my-pod",
            namespace="staging",
        )
        pod_data, ns_snapshot, history_response, ai_result = self._make_grpc_results()

        with (
            patch(
                "app.grpc_clients.analyzer_client.collect_pod", return_value=pod_data
            ),
            patch(
                "app.grpc_clients.analyzer_client.scan_namespace",
                return_value=ns_snapshot,
            ),
            patch(
                "app.grpc_clients.ai_client.get_history", return_value=history_response
            ),
            patch(
                "app.grpc_clients.ai_client.analyze_incident", return_value=ai_result
            ),
        ):
            from app.tasks import analyze_incident_task

            analyze_incident_task(
                str(job.id), str(job.user_id), job.pod_name, job.namespace
            )

        job.refresh_from_db()
        assert "confidence" in job.result
        assert "is_recurring" in job.result
        assert "recurrence_count" in job.result

    def test_task_marks_job_failed_on_exception(self):
        from core.models import AnalysisJob

        job = AnalysisJob.objects.create(
            user_id="33333333-3333-3333-3333-333333333333",
            pod_name="bad-pod",
            namespace="default",
        )

        with patch(
            "app.grpc_clients.analyzer_client.collect_pod",
            side_effect=Exception("gRPC down"),
        ):
            from app.tasks import analyze_incident_task

            with pytest.raises(Exception, match="gRPC down"):
                analyze_incident_task(
                    str(job.id), str(job.user_id), job.pod_name, job.namespace
                )

        job.refresh_from_db()
        assert job.status == AnalysisJob.Status.FAILED
        assert "gRPC down" in job.error
