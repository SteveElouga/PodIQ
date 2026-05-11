"""
Tests de la query analysisHistory.
Le client gRPC ai_client est entièrement mocké.
"""
import time
from types import SimpleNamespace
from unittest.mock import patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_history_item(
    id="item-uuid-1",
    pod_name="my-pod",
    namespace="default",
    error_type="CrashLoopBackOff",
    root_cause="Missing env",
    solution="Add env var",
    confidence="high",
    is_recurring=True,
    recurrence_count=3,
    created_at=None,
):
    return SimpleNamespace(
        id=id,
        pod_name=pod_name,
        namespace=namespace,
        error_type=error_type,
        root_cause=root_cause,
        solution=solution,
        confidence=confidence,
        is_recurring=is_recurring,
        recurrence_count=recurrence_count,
        created_at=created_at or int(time.time()),
    )


def make_history_response(items=None):
    return SimpleNamespace(items=items or [])


# ── analysisHistory ───────────────────────────────────────────────────────────

class TestAnalysisHistoryQuery:
    def _run(self, items=None, pod_name="my-pod", namespace="default", limit=10):
        response = make_history_response(items=items or [])
        with patch("app.graphql.queries.history.ai_client.get_history", return_value=response):
            from app.graphql.queries.history import _analysis_history as analysis_history
            return analysis_history(info=None, pod_name=pod_name, namespace=namespace, limit=limit)

    def test_returns_empty_list_when_no_history(self):
        result = self._run(items=[])
        assert result == []

    def test_returns_list_of_history_items(self):
        items = [make_history_item(), make_history_item(id="item-uuid-2")]
        result = self._run(items=items)
        assert len(result) == 2

    def test_item_fields_are_mapped_correctly(self):
        item = make_history_item(
            id="abc-123",
            pod_name="api-pod",
            namespace="prod",
            error_type="OOMKilled",
            root_cause="Memory limit too low",
            solution="Increase memory limit",
            confidence="medium",
            is_recurring=False,
            recurrence_count=0,
        )
        result = self._run(items=[item])
        r = result[0]
        assert r.id == "abc-123"
        assert r.pod_name == "api-pod"
        assert r.namespace == "prod"
        assert r.error_type == "OOMKilled"
        assert r.root_cause == "Memory limit too low"
        assert r.solution == "Increase memory limit"
        assert r.confidence == "medium"
        assert r.is_recurring is False
        assert r.recurrence_count == 0

    def test_created_at_is_iso_string(self):
        ts = 1747000000
        item = make_history_item(created_at=ts)
        result = self._run(items=[item])
        created_at = result[0].created_at
        assert isinstance(created_at, str)
        assert "T" in created_at or "-" in created_at

    def test_get_history_called_with_correct_args(self):
        with patch("app.graphql.queries.history.ai_client.get_history",
                   return_value=make_history_response()) as mock_fn:
            from app.graphql.queries.history import _analysis_history as analysis_history
            analysis_history(info=None, pod_name="target-pod", namespace="staging", limit=5)

        mock_fn.assert_called_once_with(pod_name="target-pod", namespace="staging", limit=5)

    def test_default_limit_is_ten(self):
        with patch("app.graphql.queries.history.ai_client.get_history",
                   return_value=make_history_response()) as mock_fn:
            from app.graphql.queries.history import _analysis_history as analysis_history
            analysis_history(info=None, pod_name="pod", namespace="ns")

        call_kwargs = mock_fn.call_args[1]
        assert call_kwargs["limit"] == 10

    def test_multiple_items_preserve_order(self):
        ts_old = int(time.time()) - 3600
        ts_new = int(time.time())
        items = [
            make_history_item(id="new", created_at=ts_new),
            make_history_item(id="old", created_at=ts_old),
        ]
        result = self._run(items=items)
        assert result[0].id == "new"
        assert result[1].id == "old"
