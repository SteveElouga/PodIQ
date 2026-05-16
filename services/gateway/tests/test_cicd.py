"""
Unit tests for POST /api/v1/cicd/scan.
All gRPC clients are fully mocked — no network or database required.
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import grpc
import pytest
from django.test import Client
from django.test.client import Client as DjangoClient

from app.api_codes import ErrorCode
from tests.grpc_fake import FakeRpcError

VALID_KEY = "raw-api-key-test-1234567890abcdef"
VALID_USER_ID = "user-uuid-cicd-test"
SCAN_URL = "/api/v1/cicd/scan"

SAMPLE_YAML = """\
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


# ── Helpers ───────────────────────────────────────────────────────────────────


def valid_api_key_response(user_id: str = VALID_USER_ID) -> SimpleNamespace:
    return SimpleNamespace(valid=True, user_id=user_id, key_id="key-id-123", error="")


def invalid_api_key_response(error: str = "Invalid key") -> SimpleNamespace:
    return SimpleNamespace(valid=False, user_id="", key_id="", error=error)


def make_parsed_manifest(
    raw_config: str = '{"image":"nginx:latest"}',
) -> SimpleNamespace:
    return SimpleNamespace(
        name="my-app",
        kind="Deployment",
        raw_config=raw_config,
        namespace="default",
    )


def make_risk(
    severity: str = "high",
    category: str = "image_tag",
    description: str = "Using :latest",
    fix: str = "Pin image tag",
) -> SimpleNamespace:
    return SimpleNamespace(
        severity=severity, category=category, description=description, fix=fix
    )


def make_scan_result(
    risk_level: str = "warning",
    summary: str = "Image tag not pinned",
    risks: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        risk_level=risk_level,
        summary=summary,
        risks=risks if risks is not None else [make_risk()],
    )


def post(client: DjangoClient, body: dict, api_key: str = VALID_KEY) -> Any:
    return client.post(
        SCAN_URL,
        data=json.dumps(body),
        content_type="application/json",
        HTTP_X_API_KEY=api_key,
    )


def _full_scan_patches(parsed=None, scan_result=None):
    parsed = parsed or make_parsed_manifest()
    scan_result = scan_result or make_scan_result()
    return (
        patch(
            "app.api.cicd.auth_client.validate_api_key",
            return_value=valid_api_key_response(),
        ),
        patch("app.api.cicd.analyzer_client.parse_manifest", return_value=parsed),
        patch("app.api.cicd.ai_client.scan_manifest", return_value=scan_result),
    )


# ── Authentication ─────────────────────────────────────────────────────────────


class TestCicdAuth:
    def test_missing_api_key_returns_401(self, client: Client):
        response = client.post(
            SCAN_URL,
            data=json.dumps({"yaml_content": SAMPLE_YAML}),
            content_type="application/json",
        )
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == ErrorCode.TOKEN_MISSING

    def test_empty_api_key_returns_401(self, client: Client):
        response = client.post(
            SCAN_URL,
            data=json.dumps({"yaml_content": SAMPLE_YAML}),
            content_type="application/json",
            HTTP_X_API_KEY="",
        )
        assert response.status_code == 401

    def test_invalid_api_key_returns_401(self, client: Client):
        with patch(
            "app.api.cicd.auth_client.validate_api_key",
            return_value=invalid_api_key_response(),
        ):
            response = post(client, {"yaml_content": SAMPLE_YAML}, api_key="wrong-key")
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == ErrorCode.TOKEN_INVALID

    def test_revoked_api_key_returns_401(self, client: Client):
        with patch(
            "app.api.cicd.auth_client.validate_api_key",
            return_value=invalid_api_key_response(error="Key revoked"),
        ):
            response = post(client, {"yaml_content": SAMPLE_YAML})
        assert response.status_code == 401

    def test_auth_grpc_unavailable_returns_502(self, client: Client):
        with patch(
            "app.api.cicd.auth_client.validate_api_key",
            side_effect=FakeRpcError(grpc.StatusCode.UNAVAILABLE),
        ):
            response = post(client, {"yaml_content": SAMPLE_YAML})
        assert response.status_code == 502
        data = response.json()
        assert data["code"] == ErrorCode.AUTH_GRPC


# ── Input validation ───────────────────────────────────────────────────────────


class TestCicdInputValidation:
    def test_get_method_not_allowed(self, client: Client):
        response = client.get(SCAN_URL)
        assert response.status_code == 405

    def test_missing_yaml_content_returns_400(self, client: Client):
        with patch(
            "app.api.cicd.auth_client.validate_api_key",
            return_value=valid_api_key_response(),
        ):
            response = post(client, {})
        assert response.status_code == 400
        data = response.json()
        assert data["code"] == ErrorCode.VALIDATION

    def test_empty_yaml_content_returns_400(self, client: Client):
        with patch(
            "app.api.cicd.auth_client.validate_api_key",
            return_value=valid_api_key_response(),
        ):
            response = post(client, {"yaml_content": "   "})
        assert response.status_code == 400

    def test_invalid_json_body_returns_400(self, client: Client):
        with patch(
            "app.api.cicd.auth_client.validate_api_key",
            return_value=valid_api_key_response(),
        ):
            response = client.post(
                SCAN_URL,
                data="not-json",
                content_type="application/json",
                HTTP_X_API_KEY=VALID_KEY,
            )
        assert response.status_code == 400

    def test_analyzer_invalid_argument_returns_400(self, client: Client):
        with (
            patch(
                "app.api.cicd.auth_client.validate_api_key",
                return_value=valid_api_key_response(),
            ),
            patch(
                "app.api.cicd.analyzer_client.parse_manifest",
                side_effect=FakeRpcError(
                    grpc.StatusCode.INVALID_ARGUMENT, "Invalid YAML"
                ),
            ),
        ):
            response = post(client, {"yaml_content": "bad: yaml: :"})
        assert response.status_code == 400


# ── Scan results ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCicdScanResults:
    def test_safe_manifest_returns_exit_code_0(self, client: Client):
        p, a, s = _full_scan_patches(
            scan_result=make_scan_result(risk_level="safe", risks=[])
        )
        with p, a, s:
            response = post(client, {"yaml_content": SAMPLE_YAML})
        assert response.status_code == 200
        data = response.json()
        assert data["exit_code"] == 0
        assert data["risk_level"] == "safe"

    def test_warning_manifest_returns_exit_code_1(self, client: Client):
        p, a, s = _full_scan_patches(scan_result=make_scan_result(risk_level="warning"))
        with p, a, s:
            response = post(client, {"yaml_content": SAMPLE_YAML})
        assert response.status_code == 200
        data = response.json()
        assert data["exit_code"] == 1
        assert data["risk_level"] == "warning"

    def test_block_manifest_returns_exit_code_2(self, client: Client):
        p, a, s = _full_scan_patches(
            scan_result=make_scan_result(
                risk_level="block",
                summary="Critical security issues found",
                risks=[make_risk(severity="critical", category="security")],
            )
        )
        with p, a, s:
            response = post(client, {"yaml_content": SAMPLE_YAML})
        assert response.status_code == 200
        data = response.json()
        assert data["exit_code"] == 2
        assert data["risk_level"] == "block"

    def test_response_contains_risks_list(self, client: Client):
        risk = make_risk(
            severity="high",
            category="image_tag",
            description="latest tag",
            fix="Pin it",
        )
        p, a, s = _full_scan_patches(scan_result=make_scan_result(risks=[risk]))
        with p, a, s:
            response = post(client, {"yaml_content": SAMPLE_YAML})
        data = response.json()
        assert len(data["risks"]) == 1
        assert data["risks"][0]["severity"] == "high"
        assert data["risks"][0]["category"] == "image_tag"
        assert data["risks"][0]["description"] == "latest tag"
        assert data["risks"][0]["fix"] == "Pin it"

    def test_response_contains_summary(self, client: Client):
        p, a, s = _full_scan_patches(scan_result=make_scan_result(summary="All good"))
        with p, a, s:
            response = post(client, {"yaml_content": SAMPLE_YAML})
        data = response.json()
        assert data["summary"] == "All good"

    def test_manifest_type_is_forwarded(self, client: Client):
        p, a, s = _full_scan_patches()
        with p, a as mock_parse, s:
            post(client, {"yaml_content": SAMPLE_YAML, "manifest_type": "CronJob"})
        mock_parse.assert_called_once_with(
            yaml_content=SAMPLE_YAML.strip(), manifest_type="CronJob"
        )

    def test_manifest_type_defaults_to_empty_string(self, client: Client):
        p, a, s = _full_scan_patches()
        with p, a as mock_parse, s:
            post(client, {"yaml_content": SAMPLE_YAML})
        mock_parse.assert_called_once_with(
            yaml_content=SAMPLE_YAML.strip(), manifest_type=""
        )

    def test_empty_risks_list_is_valid(self, client: Client):
        p, a, s = _full_scan_patches(
            scan_result=make_scan_result(risk_level="safe", risks=[])
        )
        with p, a, s:
            response = post(client, {"yaml_content": SAMPLE_YAML})
        data = response.json()
        assert data["risks"] == []

    def test_analyzer_grpc_unavailable_returns_502(self, client: Client):
        with (
            patch(
                "app.api.cicd.auth_client.validate_api_key",
                return_value=valid_api_key_response(),
            ),
            patch(
                "app.api.cicd.analyzer_client.parse_manifest",
                side_effect=FakeRpcError(grpc.StatusCode.UNAVAILABLE),
            ),
        ):
            response = post(client, {"yaml_content": SAMPLE_YAML})
        assert response.status_code == 502
        data = response.json()
        assert data["code"] == ErrorCode.ANALYZER_GRPC

    def test_ai_grpc_unavailable_returns_502(self, client: Client):
        with (
            patch(
                "app.api.cicd.auth_client.validate_api_key",
                return_value=valid_api_key_response(),
            ),
            patch(
                "app.api.cicd.analyzer_client.parse_manifest",
                return_value=make_parsed_manifest(),
            ),
            patch(
                "app.api.cicd.ai_client.scan_manifest",
                side_effect=FakeRpcError(grpc.StatusCode.UNAVAILABLE),
            ),
        ):
            response = post(client, {"yaml_content": SAMPLE_YAML})
        assert response.status_code == 502
        data = response.json()
        assert data["code"] == ErrorCode.AI_GRPC

    def test_unknown_risk_level_maps_to_exit_code_2(self, client: Client):
        p, a, s = _full_scan_patches(scan_result=make_scan_result(risk_level="unknown"))
        with p, a, s:
            response = post(client, {"yaml_content": SAMPLE_YAML})
        data = response.json()
        assert data["exit_code"] == 2
