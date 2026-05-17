from stubs.ai import ai_pb2

SYSTEM = """\
You are a senior Kubernetes reliability and security expert.
Review Kubernetes manifests BEFORE deployment and identify configuration risks.
CRITICAL RULE: Base your analysis STRICTLY on what is explicitly present or absent in the manifest.
Never invent risks for fields or values that do not exist in the manifest.
Always respond ONLY with a valid JSON object. No text outside the JSON.\
"""


def build(request: ai_pb2.ManifestScanRequest) -> str:
    return f"""\
Review the following Kubernetes manifest for risks before deployment.

=== MANIFEST CONTENT ===
{request.parsed_manifest}

=== RELATED INCIDENT HISTORY ===
{_format_history(request.related_history)}

Check ONLY for issues that are DIRECTLY VISIBLE in the manifest above:
- image_tag: image using ":latest" or a mutable/unversioned tag
- memory: container missing resources.limits.memory or resources.requests.memory
- resource: container missing CPU limits or requests
- probe: container missing livenessProbe or readinessProbe
- security: securityContext with privileged:true, runAsRoot:true, or allowPrivilegeEscalation:true
- sensitive_credentials: env var with a hardcoded secret value (password, token, key) explicitly written in the manifest
DO NOT flag "sensitive_credentials" unless an env var with a plaintext secret VALUE is actually present in the manifest.

risk_level rules:
- "block" if any critical severity risk is found
- "warning" if only medium/high risks are found
- "safe" if no significant risk is found

Return ONLY this JSON (risks list may be empty for safe manifests):
{{
  "risk_level": "safe | warning | block",
  "summary": "one sentence summary of the main risk found",
  "risks": [
    {{
      "severity": "low | medium | high | critical",
      "category": "image_tag | memory | resource | probe | security | sensitive_credentials",
      "description": "exact issue found in the manifest",
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
