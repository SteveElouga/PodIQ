"""
Unit tests for build_namespace_context.
No gRPC mock or database — pure data transformation.
CORRELATION_WINDOW_SECONDS is patched to 900 s (15 min) in every test.
"""
from types import SimpleNamespace
from unittest.mock import patch

REF_TS = 1_700_000_000
WINDOW_SEC = 900


def _pod(name: str, has_errors: bool = False, last_restart_time: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        pod_name=name,
        status="CrashLoopBackOff" if has_errors else "Running",
        has_errors=has_errors,
        last_restart_time=last_restart_time,
    )


def _snapshot(pods: list, collected_at: int = REF_TS) -> SimpleNamespace:
    return SimpleNamespace(pods=pods, collected_at=collected_at)


def _run(snapshot, target_pod_name: str):
    with patch("app.namespace_correlation.settings") as mock_settings:
        mock_settings.CORRELATION_WINDOW_SECONDS = WINDOW_SEC
        from app.namespace_correlation import build_namespace_context
        return build_namespace_context(snapshot, target_pod_name)


class TestBuildNamespaceContext:
    def test_empty_snapshot_returns_empty_list(self):
        result = _run(_snapshot([]), "my-pod")
        assert result == []

    def test_target_pod_excluded(self):
        snap = _snapshot([_pod("my-pod"), _pod("other-pod")])
        result = _run(snap, "my-pod")
        names = [p.pod_name for p in result]
        assert "my-pod" not in names
        assert "other-pod" in names

    def test_pod_inside_window_marked_correctly(self):
        snap = _snapshot([_pod("peer", has_errors=True, last_restart_time=REF_TS - 400)])
        (peer,) = _run(snap, "target")
        assert peer.in_correlation_window is True
        assert peer.seconds_before_reference == 400

    def test_pod_outside_window_marked_correctly(self):
        snap = _snapshot([_pod("old-pod", has_errors=True, last_restart_time=REF_TS - 1000)])
        (old,) = _run(snap, "target")
        assert old.in_correlation_window is False
        assert old.seconds_before_reference == 0

    def test_pod_exactly_at_window_boundary_is_inside(self):
        snap = _snapshot([_pod("edge", has_errors=True, last_restart_time=REF_TS - WINDOW_SEC)])
        (edge,) = _run(snap, "target")
        assert edge.in_correlation_window is True
        assert edge.seconds_before_reference == WINDOW_SEC

    def test_pod_one_second_past_boundary_is_outside(self):
        snap = _snapshot([_pod("just-out", has_errors=True, last_restart_time=REF_TS - WINDOW_SEC - 1)])
        (just_out,) = _run(snap, "target")
        assert just_out.in_correlation_window is False

    def test_pod_with_no_restart_time_is_outside_window(self):
        snap = _snapshot([_pod("healthy", has_errors=False, last_restart_time=0)])
        (healthy,) = _run(snap, "target")
        assert healthy.in_correlation_window is False
        assert healthy.seconds_before_reference == 0

    def test_pod_restart_after_reference_is_outside_window(self):
        snap = _snapshot([_pod("future", has_errors=True, last_restart_time=REF_TS + 60)])
        (future,) = _run(snap, "target")
        assert future.in_correlation_window is False

    def test_snapshot_without_collected_at_disables_window(self):
        snap = _snapshot([_pod("peer", has_errors=True, last_restart_time=REF_TS - 100)], collected_at=0)
        (peer,) = _run(snap, "target")
        assert peer.in_correlation_window is False

    def test_sorting_in_window_with_errors_first(self):
        pods = [
            _pod("healthy-out", has_errors=False, last_restart_time=0),
            _pod("error-out", has_errors=True, last_restart_time=REF_TS - 1000),
            _pod("error-in", has_errors=True, last_restart_time=REF_TS - 200),
            _pod("healthy-in", has_errors=False, last_restart_time=REF_TS - 100),
        ]
        result = _run(_snapshot(pods), "target")
        names = [p.pod_name for p in result]
        assert names.index("error-in") < names.index("healthy-in")
        assert names.index("error-in") < names.index("error-out")
        assert names.index("healthy-in") < names.index("healthy-out")

    def test_pod_context_fields_populated(self):
        snap = _snapshot([_pod("worker", has_errors=True, last_restart_time=REF_TS - 300)])
        (worker,) = _run(snap, "target")
        assert worker.pod_name == "worker"
        assert worker.status == "CrashLoopBackOff"
        assert worker.had_issues is True
        assert worker.issue_timestamp == REF_TS - 300
