from stubs.ai import ai_pb2

SYSTEM = """\
You are a senior Site Reliability Engineer specialized in Kubernetes with 10+ years of experience.
Analyze Kubernetes pod failures and provide clear, actionable diagnoses.
Always respond ONLY with a valid JSON object. No text outside the JSON.\
"""


def build(request: ai_pb2.IncidentRequest) -> str:
    return f"""\
Analyze the following Kubernetes incident.

Pod: {request.pod_name} | Namespace: {request.namespace} | Status: {request.status}

=== LOGS ===
{request.logs}

=== EVENTS ===
{request.events}

=== INCIDENT HISTORY (last {len(request.history)} occurrences) ===
{_format_history(request.history)}

=== NAMESPACE CONTEXT (other pods; temporal correlation vs incident snapshot time) ===
{_format_namespace_context(request.namespace_context)}

When "within correlation window" is yes, the peer pod had a recorded issue within seconds_before_reference
of the namespace snapshot time — consider shared failures (e.g. dependency outage, rollout).

Return ONLY this JSON:
{{
  "error_type": "short error category (e.g. CrashLoopBackOff, OOMKilled)",
  "root_cause": "one sentence — the probable root cause",
  "explanation": "2-3 sentences explaining what happened",
  "solution": "actionable solution as a single string (no list, no array)",
  "confidence": "high | medium | low",
  "is_recurring": true or false,
  "correlated_service": "pod name if another pod caused this, else null",
  "correlation_explanation": "one sentence if correlated, else null"
}}\
"""


def _format_history(history: list[ai_pb2.PastIncident]) -> str:
    if not history:
        return "No previous incidents recorded."
    lines = []
    for i, inc in enumerate(history, 1):
        lines.append(
            f"{i}. [{inc.error_type}] {inc.root_cause} — Solution: {inc.solution}"
        )
    return "\n".join(lines)


def _format_namespace_context(pods: list[ai_pb2.PodContext]) -> str:
    if not pods:
        return "No namespace context available."
    lines = []
    for pod in pods:
        state = "had issues" if pod.had_issues else "healthy"
        window = "yes" if pod.in_correlation_window else "no"
        ts_note = (
            f"issue_ts_unix={pod.issue_timestamp}"
            if pod.issue_timestamp
            else "issue_ts_unix=n/a"
        )
        before = (
            f"{pod.seconds_before_reference}s before snapshot"
            if pod.in_correlation_window and pod.seconds_before_reference
            else ""
        )
        extra = f" | correlation_window={window}"
        if before:
            extra += f" | {before}"
        lines.append(f"- {pod.pod_name}: {pod.status} ({state}) | {ts_note}{extra}")
    return "\n".join(lines)
