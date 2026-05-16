"""
analyzeIncident mutation tests.
All gRPC clients are mocked; no database required.
require_auth is mocked to simulate an authenticated user.
"""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

MOCK_USER_ID = "user-uuid-test"


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_pod_data(pod_name="my-pod", namespace="default", status="CrashLoopBackOff",
                  logs="error: db not found", events="BackOff restarting"):
    return SimpleNamespace(
        pod_name=pod_name,
        namespace=namespace,
        status=status,
        logs=logs,
        events=events,
    )


def make_namespace_snapshot(pods=None):
    return SimpleNamespace(pods=pods or [])


def make_analysis_result(
    error_type="CrashLoopBackOff",
    root_cause="Missing DATABASE_URL",
    explanation="Pod crashes on startup",
    solution="Add DATABASE_URL to secret",
    confidence="high",
    is_recurring=False,
    recurrence_count=0,
    correlated_service="",
    correlation_explanation="",
):
    return SimpleNamespace(
        error_type=error_type,
        root_cause=root_cause,
        explanation=explanation,
        solution=solution,
        confidence=confidence,
        is_recurring=is_recurring,
        recurrence_count=recurrence_count,
        correlated_service=correlated_service,
        correlation_explanation=correlation_explanation,
    )


# ── analyzeIncident ───────────────────────────────────────────────────────────

class TestAnalyzeIncidentMutation:
    def _run(self, pod_data=None, ns_snapshot=None, ai_result=None):
        pod_data = pod_data or make_pod_data()
        ns_snapshot = ns_snapshot or make_namespace_snapshot()
        ai_result = ai_result or make_analysis_result()

        with patch("app.graphql.mutations.analyze.require_auth", return_value=MOCK_USER_ID), \
             patch("app.graphql.mutations.analyze.analyzer_client.collect_pod", return_value=pod_data), \
             patch("app.graphql.mutations.analyze.analyzer_client.scan_namespace", return_value=ns_snapshot), \
             patch("app.graphql.mutations.analyze.ai_client.analyze_incident", return_value=ai_result):

            from app.graphql.mutations.analyze import _analyze_incident as analyze_incident
            return analyze_incident(info=None, pod_name="my-pod", namespace="default")

    def test_returns_analysis_result_type(self):
        result = self._run()
        assert result.error_type == "CrashLoopBackOff"
        assert result.root_cause == "Missing DATABASE_URL"
        assert result.solution == "Add DATABASE_URL to secret"
        assert result.confidence == "high"

    def test_is_recurring_false_by_default(self):
        result = self._run()
        assert result.is_recurring is False
        assert result.recurrence_count == 0

    def test_is_recurring_true_when_set(self):
        ai = make_analysis_result(is_recurring=True, recurrence_count=3)
        result = self._run(ai_result=ai)
        assert result.is_recurring is True
        assert result.recurrence_count == 3

    def test_correlated_service_is_none_when_empty(self):
        ai = make_analysis_result(correlated_service="", correlation_explanation="")
        result = self._run(ai_result=ai)
        assert result.correlated_service is None
        assert result.correlation_explanation is None

    def test_correlated_service_is_set_when_present(self):
        ai = make_analysis_result(
            correlated_service="postgres-svc",
            correlation_explanation="OOMKilled 5 min before",
        )
        result = self._run(ai_result=ai)
        assert result.correlated_service == "postgres-svc"
        assert result.correlation_explanation == "OOMKilled 5 min before"

    def test_collect_pod_called_with_correct_args(self):
        with patch("app.graphql.mutations.analyze.require_auth", return_value=MOCK_USER_ID), \
             patch("app.graphql.mutations.analyze.analyzer_client.collect_pod", return_value=make_pod_data()) as mock_collect, \
             patch("app.graphql.mutations.analyze.analyzer_client.scan_namespace", return_value=make_namespace_snapshot()), \
             patch("app.graphql.mutations.analyze.ai_client.analyze_incident", return_value=make_analysis_result()):

            from app.graphql.mutations.analyze import _analyze_incident as analyze_incident
            analyze_incident(info=None, pod_name="target-pod", namespace="staging")

        mock_collect.assert_called_once_with(pod_name="target-pod", namespace="staging")

    def test_scan_namespace_called_with_correct_namespace(self):
        with patch("app.graphql.mutations.analyze.require_auth", return_value=MOCK_USER_ID), \
             patch("app.graphql.mutations.analyze.analyzer_client.collect_pod", return_value=make_pod_data()), \
             patch("app.graphql.mutations.analyze.analyzer_client.scan_namespace", return_value=make_namespace_snapshot()) as mock_ns, \
             patch("app.graphql.mutations.analyze.ai_client.analyze_incident", return_value=make_analysis_result()):

            from app.graphql.mutations.analyze import _analyze_incident as analyze_incident
            analyze_incident(info=None, pod_name="my-pod", namespace="production")

        call_kwargs = mock_ns.call_args[1]
        assert call_kwargs["namespace"] == "production"

    def test_namespace_context_excludes_analyzed_pod(self):
        """Other namespace pods are included in context; the analyzed pod is excluded."""
        pods = [
            SimpleNamespace(pod_name="my-pod", status="Running", has_errors=False, last_restart_time=0),
            SimpleNamespace(pod_name="other-pod", status="CrashLoopBackOff", has_errors=True, last_restart_time=0),
        ]
        ns_snapshot = make_namespace_snapshot(pods=pods)

        captured = {}

        def capture_request(request):
            captured["ctx"] = list(request.namespace_context)
            return make_analysis_result()

        with patch("app.graphql.mutations.analyze.require_auth", return_value=MOCK_USER_ID), \
             patch("app.graphql.mutations.analyze.analyzer_client.collect_pod", return_value=make_pod_data(pod_name="my-pod")), \
             patch("app.graphql.mutations.analyze.analyzer_client.scan_namespace", return_value=ns_snapshot), \
             patch("app.graphql.mutations.analyze.ai_client.analyze_incident", side_effect=capture_request):

            from app.graphql.mutations.analyze import _analyze_incident as analyze_incident
            analyze_incident(info=None, pod_name="my-pod", namespace="default")

        pod_names_in_ctx = [p.pod_name for p in captured["ctx"]]
        assert "my-pod" not in pod_names_in_ctx
        assert "other-pod" in pod_names_in_ctx


class TestAnalyzeIncidentAuth:
    def test_raises_permission_error_without_token(self):
        import pytest
        from app.graphql.mutations.analyze import _analyze_incident as analyze_incident
        with pytest.raises(PermissionError):
            analyze_incident(info=None, pod_name="pod", namespace="default")
