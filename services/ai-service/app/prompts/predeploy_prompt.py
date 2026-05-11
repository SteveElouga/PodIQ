from stubs.ai import ai_pb2

SYSTEM = """\
You are a senior Kubernetes reliability and security expert.
Review Kubernetes manifests BEFORE deployment and identify configuration risks.
Always respond ONLY with a valid JSON object. No text outside the JSON.\
"""


def build(request: ai_pb2.ManifestScanRequest) -> str:
    return f"""\
Review the following Kubernetes manifest for risks before deployment.

=== CONFIGURATION ===
{request.parsed_manifest}

=== RELATED INCIDENT HISTORY ===
{_format_history(request.related_history)}

Analyze for: missing_env, memory limits, probe config, image tag,
             missing secrets, resource requests, security context.

Return ONLY this JSON:
{{
  "risk_level": "safe | warning | block",
  "summary": "one sentence summary of the main risk",
  "risks": [
    {{
      "severity": "low | medium | high | critical",
      "category": "missing_env | probe | image_tag | memory | security | resource",
      "description": "what is wrong",
      "fix": "exact fix to apply"
    }}
  ]
}}\
"""


def _format_history(history: list[ai_pb2.PastIncident]) -> str:
    if not history:
        return "No related incidents in history."
    lines = []
    for i, inc in enumerate(history, 1):
        lines.append(f"{i}. [{inc.error_type}] {inc.root_cause}")
    return "\n".join(lines)
