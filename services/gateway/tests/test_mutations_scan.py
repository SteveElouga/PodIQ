"""
Tests de la mutation scanManifest.
Les clients gRPC sont entièrement mockés.
require_auth est mocké pour simuler un utilisateur authentifié.
"""
from types import SimpleNamespace
from unittest.mock import patch

MOCK_USER_ID = "user-uuid-test"


# ── Helpers ───────────────────────────────────────────────────────────────────

SAMPLE_YAML = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      containers:
        - name: app
          image: nginx:latest
"""


def make_parsed_manifest(name="my-app", kind="Deployment", raw_config='{"image":"nginx:latest"}'):
    return SimpleNamespace(
        name=name,
        kind=kind,
        raw_config=raw_config,
        namespace="default",
        image="nginx:latest",
        has_fixed_tag=False,
        env_vars=[],
        has_limits=False,
        has_probes=False,
    )


def make_risk(severity="high", category="image_tag", description="Using :latest", fix="Pin image tag"):
    return SimpleNamespace(severity=severity, category=category, description=description, fix=fix)


def make_scan_result(risk_level="warning", summary="Image tag not pinned", risks=None):
    return SimpleNamespace(
        risk_level=risk_level,
        summary=summary,
        risks=risks if risks is not None else [make_risk()],
    )


# ── scanManifest ──────────────────────────────────────────────────────────────

class TestScanManifestMutation:
    def _run(self, parsed=None, scan_result=None, yaml_content=SAMPLE_YAML, manifest_type="Deployment"):
        parsed = parsed or make_parsed_manifest()
        scan_result = scan_result or make_scan_result()

        with patch("app.graphql.mutations.scan_manifest.require_auth", return_value=MOCK_USER_ID), \
             patch("app.graphql.mutations.scan_manifest.analyzer_client.parse_manifest", return_value=parsed), \
             patch("app.graphql.mutations.scan_manifest.ai_client.scan_manifest", return_value=scan_result):

            from app.graphql.mutations.scan_manifest import _scan_manifest as scan_manifest
            return scan_manifest(info=None, yaml_content=yaml_content, manifest_type=manifest_type)

    def test_returns_scan_result_type(self):
        result = self._run()
        assert result.risk_level == "warning"
        assert result.summary == "Image tag not pinned"

    def test_risks_are_mapped_correctly(self):
        risks = [
            make_risk(severity="critical", category="missing_env", description="No DATABASE_URL", fix="Add it"),
            make_risk(severity="medium", category="probe", description="No readiness probe", fix="Add probe"),
        ]
        result = self._run(scan_result=make_scan_result(risk_level="block", risks=risks))
        assert len(result.risks) == 2
        assert result.risks[0].severity == "critical"
        assert result.risks[0].category == "missing_env"
        assert result.risks[1].severity == "medium"

    def test_safe_result_has_no_risks(self):
        result = self._run(scan_result=make_scan_result(risk_level="safe", summary="OK", risks=[]))
        assert result.risk_level == "safe"
        assert result.risks == []

    def test_parse_manifest_called_with_yaml_content(self):
        yaml = "apiVersion: v1\nkind: Pod"
        with patch("app.graphql.mutations.scan_manifest.require_auth", return_value=MOCK_USER_ID), \
             patch("app.graphql.mutations.scan_manifest.analyzer_client.parse_manifest",
                   return_value=make_parsed_manifest()) as mock_parse, \
             patch("app.graphql.mutations.scan_manifest.ai_client.scan_manifest",
                   return_value=make_scan_result()):

            from app.graphql.mutations.scan_manifest import _scan_manifest as scan_manifest
            scan_manifest(info=None, yaml_content=yaml, manifest_type="Pod")

        mock_parse.assert_called_once_with(yaml_content=yaml, manifest_type="Pod")

    def test_ai_scan_receives_raw_config(self):
        parsed = make_parsed_manifest(raw_config='{"image":"nginx:1.25"}')
        captured = {}

        def capture(*args, **kwargs):
            captured["manifest"] = kwargs.get("parsed_manifest") or args[0]
            return make_scan_result()

        with patch("app.graphql.mutations.scan_manifest.require_auth", return_value=MOCK_USER_ID), \
             patch("app.graphql.mutations.scan_manifest.analyzer_client.parse_manifest", return_value=parsed), \
             patch("app.graphql.mutations.scan_manifest.ai_client.scan_manifest", side_effect=capture):

            from app.graphql.mutations.scan_manifest import _scan_manifest as scan_manifest
            scan_manifest(info=None, yaml_content=SAMPLE_YAML, manifest_type="Deployment")

        assert captured["manifest"] == '{"image":"nginx:1.25"}'


class TestScanManifestAuth:
    def test_raises_permission_error_without_token(self):
        import pytest
        from app.graphql.mutations.scan_manifest import _scan_manifest as scan_manifest
        with pytest.raises(PermissionError):
            scan_manifest(info=None, yaml_content="apiVersion: v1", manifest_type="Pod")

    def test_block_risk_level_propagated(self):
        result = self._run(scan_result=make_scan_result(risk_level="block", summary="Dangerous config"))
        assert result.risk_level == "block"

    def test_risk_fix_is_propagated(self):
        risks = [make_risk(fix="kubectl set image deployment/app app=nginx:1.25")]
        result = self._run(scan_result=make_scan_result(risks=risks))
        assert "nginx:1.25" in result.risks[0].fix
