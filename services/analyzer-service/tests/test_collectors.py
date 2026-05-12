"""
Tests unitaires des collectors pod et namespace.
Le chemin stub (STUB_MODE=True) est testé sans dépendance Kubernetes.
Le chemin réel est testé avec l'API K8s entièrement mockée.
"""
import time
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from kubernetes.client.exceptions import ApiException


# ── pod_collector ──────────────────────────────────────────────────────────────

class TestStubCollectPod:
    def test_returns_correct_pod_name_and_namespace(self):
        with patch("app.collectors.pod_collector.STUB_MODE", True):
            from app.collectors.pod_collector import collect_pod
            result = collect_pod("my-pod", "default")
        assert result["pod_name"] == "my-pod"
        assert result["namespace"] == "default"

    def test_returns_crashloopbackoff_status(self):
        with patch("app.collectors.pod_collector.STUB_MODE", True):
            from app.collectors.pod_collector import collect_pod
            result = collect_pod("any-pod", "staging")
        assert result["status"] == "CrashLoopBackOff"

    def test_logs_contain_database_error(self):
        with patch("app.collectors.pod_collector.STUB_MODE", True):
            from app.collectors.pod_collector import collect_pod
            result = collect_pod("pod", "ns")
        assert "database" in result["logs"].lower()

    def test_events_contain_backoff(self):
        with patch("app.collectors.pod_collector.STUB_MODE", True):
            from app.collectors.pod_collector import collect_pod
            result = collect_pod("pod", "ns")
        assert "BackOff" in result["events"]

    def test_describe_output_contains_pod_name(self):
        with patch("app.collectors.pod_collector.STUB_MODE", True):
            from app.collectors.pod_collector import collect_pod
            result = collect_pod("crashloop-pod", "default")
        assert "crashloop-pod" in result["describe_output"]

    def test_all_required_keys_present(self):
        with patch("app.collectors.pod_collector.STUB_MODE", True):
            from app.collectors.pod_collector import collect_pod
            result = collect_pod("pod", "ns")
        for key in ("pod_name", "namespace", "status", "logs", "events", "describe_output"):
            assert key in result


class TestRealCollectPod:
    def _mock_v1(self, logs="log line", phase="Running", events_items=None):
        v1 = MagicMock()
        v1.read_namespaced_pod_log.return_value = logs
        pod = MagicMock()
        pod.status.phase = phase
        pod.status.container_statuses = []
        v1.read_namespaced_pod.return_value = pod
        event = MagicMock()
        event.reason = "Started"
        event.message = "Container started"
        event_list = MagicMock()
        event_list.items = events_items or [event]
        v1.list_namespaced_event.return_value = event_list
        return v1

    def test_returns_pod_name_and_namespace(self):
        v1 = self._mock_v1()
        with patch("app.collectors.pod_collector.STUB_MODE", False), \
             patch("app.collectors.pod_collector._load_k8s_config"), \
             patch("app.collectors.pod_collector.client.CoreV1Api", return_value=v1):
            from app.collectors.pod_collector import collect_pod
            result = collect_pod("real-pod", "prod")
        assert result["pod_name"] == "real-pod"
        assert result["namespace"] == "prod"

    def test_returns_phase_as_status(self):
        v1 = self._mock_v1(phase="OOMKilled")
        with patch("app.collectors.pod_collector.STUB_MODE", False), \
             patch("app.collectors.pod_collector._load_k8s_config"), \
             patch("app.collectors.pod_collector.client.CoreV1Api", return_value=v1):
            from app.collectors.pod_collector import collect_pod
            result = collect_pod("pod", "ns")
        assert result["status"] == "OOMKilled"

    def test_logs_unavailable_on_api_exception(self):
        v1 = self._mock_v1()
        v1.read_namespaced_pod_log.side_effect = ApiException(status=403, reason="Forbidden")
        with patch("app.collectors.pod_collector.STUB_MODE", False), \
             patch("app.collectors.pod_collector._load_k8s_config"), \
             patch("app.collectors.pod_collector.client.CoreV1Api", return_value=v1):
            from app.collectors.pod_collector import collect_pod
            result = collect_pod("pod", "ns")
        assert "logs unavailable" in result["logs"]


# ── namespace_collector ────────────────────────────────────────────────────────

class TestStubScanNamespace:
    def test_returns_correct_namespace(self):
        with patch("app.collectors.namespace_collector.STUB_MODE", True):
            from app.collectors.namespace_collector import scan_namespace
            result = scan_namespace("default", incident_timestamp=1_700_000_000)
        assert result["namespace"] == "default"

    def test_returns_three_pods(self):
        with patch("app.collectors.namespace_collector.STUB_MODE", True):
            from app.collectors.namespace_collector import scan_namespace
            result = scan_namespace("default", incident_timestamp=1_700_000_000)
        assert len(result["pods"]) == 3

    def test_worker_pod_has_errors(self):
        with patch("app.collectors.namespace_collector.STUB_MODE", True):
            from app.collectors.namespace_collector import scan_namespace
            result = scan_namespace("default", incident_timestamp=1_700_000_000)
        worker = next(p for p in result["pods"] if "worker" in p["pod_name"])
        assert worker["has_errors"] is True

    def test_worker_restart_time_is_ref_minus_300(self):
        ref = 1_700_000_000
        with patch("app.collectors.namespace_collector.STUB_MODE", True):
            from app.collectors.namespace_collector import scan_namespace
            result = scan_namespace("default", incident_timestamp=ref)
        worker = next(p for p in result["pods"] if "worker" in p["pod_name"])
        assert worker["last_restart_time"] == ref - 300

    def test_collected_at_equals_ref_when_incident_timestamp_given(self):
        ref = 1_700_000_000
        with patch("app.collectors.namespace_collector.STUB_MODE", True):
            from app.collectors.namespace_collector import scan_namespace
            result = scan_namespace("default", incident_timestamp=ref)
        assert result["collected_at"] == ref

    def test_collected_at_falls_back_to_now_when_timestamp_zero(self):
        before = int(time.time())
        with patch("app.collectors.namespace_collector.STUB_MODE", True):
            from app.collectors.namespace_collector import scan_namespace
            result = scan_namespace("default", incident_timestamp=0)
        after = int(time.time())
        assert before <= result["collected_at"] <= after

    def test_healthy_pods_have_no_errors(self):
        with patch("app.collectors.namespace_collector.STUB_MODE", True):
            from app.collectors.namespace_collector import scan_namespace
            result = scan_namespace("default", incident_timestamp=1_700_000_000)
        healthy = [p for p in result["pods"] if not p["has_errors"]]
        assert len(healthy) == 2

    def test_all_required_keys_present_in_pods(self):
        with patch("app.collectors.namespace_collector.STUB_MODE", True):
            from app.collectors.namespace_collector import scan_namespace
            result = scan_namespace("default", incident_timestamp=1_700_000_000)
        for pod in result["pods"]:
            for key in ("pod_name", "status", "has_errors", "last_restart_time"):
                assert key in pod


class TestRealScanNamespace:
    def _mock_v1(self, pods=None):
        v1 = MagicMock()
        pod_list = MagicMock()
        pod_list.items = pods or []
        v1.list_namespaced_pod.return_value = pod_list
        return v1

    def test_returns_namespace(self):
        v1 = self._mock_v1()
        with patch("app.collectors.namespace_collector.STUB_MODE", False), \
             patch("app.collectors.namespace_collector._load_k8s_config"), \
             patch("app.collectors.namespace_collector.client.CoreV1Api", return_value=v1):
            from app.collectors.namespace_collector import scan_namespace
            result = scan_namespace("production")
        assert result["namespace"] == "production"

    def test_returns_empty_pods_on_api_exception(self):
        v1 = self._mock_v1()
        v1.list_namespaced_pod.side_effect = ApiException(status=403, reason="Forbidden")
        with patch("app.collectors.namespace_collector.STUB_MODE", False), \
             patch("app.collectors.namespace_collector._load_k8s_config"), \
             patch("app.collectors.namespace_collector.client.CoreV1Api", return_value=v1):
            from app.collectors.namespace_collector import scan_namespace
            result = scan_namespace("prod")
        assert result["pods"] == []
