"""
Unit tests for the incident and predeploy prompt builders.
Protobuf objects are imported from shared/grpc via conftest.py.
"""

from app.prompts import incident_prompt, predeploy_prompt
from stubs.ai import ai_pb2

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_incident_request(
    pod_name="my-pod",
    namespace="default",
    status="CrashLoopBackOff",
    logs="ERROR: db refused",
    events="BackOff restarting",
    history=None,
    namespace_context=None,
) -> ai_pb2.IncidentRequest:
    return ai_pb2.IncidentRequest(
        pod_name=pod_name,
        namespace=namespace,
        status=status,
        logs=logs,
        events=events,
        history=history or [],
        namespace_context=namespace_context or [],
    )


def make_past_incident(
    error_type="CrashLoopBackOff",
    root_cause="DB missing",
    solution="Add env var",
    occurred_at=0,
) -> ai_pb2.PastIncident:
    return ai_pb2.PastIncident(
        error_type=error_type,
        root_cause=root_cause,
        solution=solution,
        occurred_at=occurred_at,
    )


def make_pod_context(
    pod_name="peer-pod",
    status="Running",
    had_issues=False,
    issue_timestamp=0,
    in_correlation_window=False,
    seconds_before_reference=0,
) -> ai_pb2.PodContext:
    return ai_pb2.PodContext(
        pod_name=pod_name,
        status=status,
        had_issues=had_issues,
        issue_timestamp=issue_timestamp,
        in_correlation_window=in_correlation_window,
        seconds_before_reference=seconds_before_reference,
    )


def make_manifest_request(
    parsed_manifest='{"image": "nginx:latest"}',
    related_history=None,
) -> ai_pb2.ManifestScanRequest:
    return ai_pb2.ManifestScanRequest(
        parsed_manifest=parsed_manifest,
        related_history=related_history or [],
    )


# ── incident_prompt ───────────────────────────────────────────────────────────


class TestIncidentPromptBuild:
    def test_contains_pod_name(self):
        prompt = incident_prompt.build(make_incident_request(pod_name="crashloop-pod"))
        assert "crashloop-pod" in prompt

    def test_contains_namespace(self):
        prompt = incident_prompt.build(make_incident_request(namespace="staging"))
        assert "staging" in prompt

    def test_contains_status(self):
        prompt = incident_prompt.build(make_incident_request(status="OOMKilled"))
        assert "OOMKilled" in prompt

    def test_contains_logs(self):
        prompt = incident_prompt.build(
            make_incident_request(logs="FATAL: out of memory")
        )
        assert "FATAL: out of memory" in prompt

    def test_contains_events(self):
        prompt = incident_prompt.build(
            make_incident_request(events="Killing container")
        )
        assert "Killing container" in prompt

    def test_no_history_shows_placeholder(self):
        prompt = incident_prompt.build(make_incident_request(history=[]))
        assert "No previous incidents" in prompt

    def test_history_is_formatted(self):
        inc = make_past_incident(
            error_type="OOMKilled", root_cause="Leak", solution="Increase limit"
        )
        prompt = incident_prompt.build(make_incident_request(history=[inc]))
        assert "OOMKilled" in prompt
        assert "Leak" in prompt
        assert "Increase limit" in prompt

    def test_history_numbered(self):
        incidents = [
            make_past_incident(error_type="CrashLoop"),
            make_past_incident(error_type="OOMKilled"),
        ]
        prompt = incident_prompt.build(make_incident_request(history=incidents))
        assert "1." in prompt
        assert "2." in prompt

    def test_no_namespace_context_shows_placeholder(self):
        prompt = incident_prompt.build(make_incident_request(namespace_context=[]))
        assert "No namespace context available" in prompt

    def test_namespace_context_pod_name_appears(self):
        ctx = make_pod_context(pod_name="worker-6b8c", had_issues=True)
        prompt = incident_prompt.build(make_incident_request(namespace_context=[ctx]))
        assert "worker-6b8c" in prompt

    def test_namespace_context_in_window_shows_yes(self):
        ctx = make_pod_context(
            pod_name="peer",
            in_correlation_window=True,
            seconds_before_reference=400,
        )
        prompt = incident_prompt.build(make_incident_request(namespace_context=[ctx]))
        assert "yes" in prompt
        assert "400s before snapshot" in prompt

    def test_namespace_context_out_of_window_shows_no(self):
        ctx = make_pod_context(pod_name="peer", in_correlation_window=False)
        prompt = incident_prompt.build(make_incident_request(namespace_context=[ctx]))
        assert "no" in prompt

    def test_namespace_context_issue_timestamp_shown(self):
        ctx = make_pod_context(pod_name="peer", issue_timestamp=1_700_000_000)
        prompt = incident_prompt.build(make_incident_request(namespace_context=[ctx]))
        assert "1700000000" in prompt

    def test_namespace_context_no_timestamp_shows_na(self):
        ctx = make_pod_context(pod_name="peer", issue_timestamp=0)
        prompt = incident_prompt.build(make_incident_request(namespace_context=[ctx]))
        assert "n/a" in prompt

    def test_prompt_contains_json_schema_keys(self):
        prompt = incident_prompt.build(make_incident_request())
        for key in (
            "error_type",
            "root_cause",
            "explanation",
            "solution",
            "confidence",
        ):
            assert key in prompt

    def test_system_constant_is_non_empty_string(self):
        assert isinstance(incident_prompt.SYSTEM, str)
        assert len(incident_prompt.SYSTEM) > 0


# ── predeploy_prompt ──────────────────────────────────────────────────────────


class TestPredeployPromptBuild:
    def test_contains_parsed_manifest(self):
        prompt = predeploy_prompt.build(
            make_manifest_request(parsed_manifest='{"image":"nginx:1.25"}')
        )
        assert "nginx:1.25" in prompt

    def test_no_history_shows_placeholder(self):
        prompt = predeploy_prompt.build(make_manifest_request(related_history=[]))
        assert "No related incidents" in prompt

    def test_history_is_formatted(self):
        inc = make_past_incident(error_type="OOMKilled", root_cause="Memory leak")
        prompt = predeploy_prompt.build(make_manifest_request(related_history=[inc]))
        assert "OOMKilled" in prompt
        assert "Memory leak" in prompt

    def test_history_numbered(self):
        incidents = [make_past_incident(), make_past_incident()]
        prompt = predeploy_prompt.build(
            make_manifest_request(related_history=incidents)
        )
        assert "1." in prompt
        assert "2." in prompt

    def test_prompt_contains_json_schema_keys(self):
        prompt = predeploy_prompt.build(make_manifest_request())
        for key in ("risk_level", "summary", "risks", "severity", "category", "fix"):
            assert key in prompt

    def test_prompt_contains_risk_levels(self):
        prompt = predeploy_prompt.build(make_manifest_request())
        assert "safe" in prompt
        assert "warning" in prompt
        assert "block" in prompt

    def test_system_constant_is_non_empty_string(self):
        assert isinstance(predeploy_prompt.SYSTEM, str)
        assert len(predeploy_prompt.SYSTEM) > 0
