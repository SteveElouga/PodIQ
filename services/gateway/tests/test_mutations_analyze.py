"""
analyzeIncident mutation tests.
Mutation enqueues a Dramatiq task and returns a job_id immediately.
Agent provides raw pod data (logs, events, describe_output) — no gRPC calls to analyzer.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from graphql import GraphQLError

from app.api_codes import GRAPHQL_EXTENSION_CODE, ErrorCode
from app.auth import TokenContext

MOCK_USER_ID = "user-uuid-test"
MOCK_CTX = TokenContext(user_id=MOCK_USER_ID)
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
    def _run(
        self,
        job: MagicMock | None = None,
        user_id: str = MOCK_USER_ID,
        logs: str = "OOMKilled",
        events: str = "BackOff restarting",
        describe_output: str = "",
    ) -> dict:
        job = job or make_job()
        ctx = TokenContext(user_id=user_id)
        with (
            patch("app.graphql.mutations.analyze.require_auth", return_value=ctx),
            patch(
                "app.graphql.mutations.analyze.AnalysisJob.objects.create",
                return_value=job,
            ),
            patch(
                "app.graphql.mutations.analyze.analyze_incident_task.send"
            ) as mock_send,
        ):
            from app.graphql.mutations.analyze import _analyze_incident

            result = _analyze_incident(
                make_info(), "crashloop-pod", "default", logs, events, describe_output
            )
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

    def test_task_sent_with_raw_pod_data(self):
        job = make_job(job_id=MOCK_JOB_ID)
        data = self._run(
            job=job, logs="crash logs", events="crash events", describe_output="desc"
        )
        data["send"].assert_called_once_with(
            MOCK_JOB_ID,
            MOCK_USER_ID,
            "crashloop-pod",
            "default",
            "crash logs",
            "crash events",
            "desc",
        )

    def test_job_created_with_user_pod_namespace(self):
        with (
            patch("app.graphql.mutations.analyze.require_auth", return_value=MOCK_CTX),
            patch(
                "app.graphql.mutations.analyze.AnalysisJob.objects.create",
                return_value=make_job(),
            ) as mock_create,
            patch("app.graphql.mutations.analyze.analyze_incident_task.send"),
        ):
            from app.graphql.mutations.analyze import _analyze_incident

            _analyze_incident(make_info(), "my-pod", "staging", "", "", "")

        mock_create.assert_called_once_with(
            user_id=MOCK_USER_ID,
            workspace_id=None,
            pod_name="my-pod",
            namespace="staging",
        )


class TestAnalyzeIncidentAuth:
    def test_raises_permission_error_without_token(self):
        from app.graphql.mutations.analyze import _analyze_incident

        with pytest.raises(GraphQLError) as exc_info:
            _analyze_incident(make_info(token=None), "pod", "ns", "", "", "")
        assert (
            exc_info.value.extensions[GRAPHQL_EXTENSION_CODE] == ErrorCode.TOKEN_MISSING
        )


# ── Dramatiq task ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestAnalyzeIncidentTask:
    def _make_ai_result(self) -> SimpleNamespace:
        return SimpleNamespace(
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

    def _run_task(self, job, logs="", events="", describe="", ns_pods=""):
        with (
            patch(
                "app.grpc_clients.ai_client.get_history",
                return_value=SimpleNamespace(items=[]),
            ),
            patch(
                "app.grpc_clients.ai_client.analyze_incident",
                return_value=self._make_ai_result(),
            ),
        ):
            from app.tasks import analyze_incident_task

            analyze_incident_task(
                str(job.id),
                str(job.user_id),
                job.pod_name,
                job.namespace,
                logs,
                events,
                describe,
                ns_pods,
            )

    def test_task_marks_job_complete(self):
        from core.models import AnalysisJob

        job = AnalysisJob.objects.create(
            user_id="11111111-1111-1111-1111-111111111111",
            pod_name="crashloop-pod",
            namespace="default",
        )
        self._run_task(job, logs="OOMKilled logs", events="BackOff events")

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
        self._run_task(job)

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
            "app.grpc_clients.ai_client.get_history",
            side_effect=Exception("gRPC down"),
        ):
            from app.tasks import analyze_incident_task

            with pytest.raises(Exception, match="gRPC down"):
                analyze_incident_task(
                    str(job.id),
                    str(job.user_id),
                    job.pod_name,
                    job.namespace,
                    "",
                    "",
                    "",
                    "",
                )

        job.refresh_from_db()
        assert job.status == AnalysisJob.Status.FAILED
        assert "gRPC down" in job.error

    def test_task_passes_namespace_context_to_ai(self):
        """namespace_pods JSON is parsed and forwarded as PodContext list."""
        import json

        from core.models import AnalysisJob

        job = AnalysisJob.objects.create(
            user_id="44444444-4444-4444-4444-444444444444",
            pod_name="gateway-pod",
            namespace="production",
        )
        ns_pods = json.dumps(
            [
                {
                    "name": "auth-svc",
                    "status": "CrashLoopBackOff",
                    "has_errors": True,
                    "last_restart_time": 9999999999,
                },
                {
                    "name": "redis",
                    "status": "Running",
                    "has_errors": False,
                    "last_restart_time": 0,
                },
            ]
        )

        captured = {}

        def capture_request(req):
            captured["namespace_context"] = list(req.namespace_context)
            return self._make_ai_result()

        with (
            patch(
                "app.grpc_clients.ai_client.get_history",
                return_value=SimpleNamespace(items=[]),
            ),
            patch(
                "app.grpc_clients.ai_client.analyze_incident",
                side_effect=capture_request,
            ),
        ):
            from app.tasks import analyze_incident_task

            analyze_incident_task(
                str(job.id),
                str(job.user_id),
                job.pod_name,
                job.namespace,
                "",
                "",
                "",
                ns_pods,
            )

        assert len(captured["namespace_context"]) == 2
        names = [c.pod_name for c in captured["namespace_context"]]
        assert "auth-svc" in names
        assert "redis" in names
