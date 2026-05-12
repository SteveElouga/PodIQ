"""
Unit tests for app/parsers/yaml_parser.py.
Pure functions — no Kubernetes or database dependency.
"""
from app.parsers.yaml_parser import parse_manifest

DEPLOYMENT_YAML = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  namespace: staging
spec:
  template:
    spec:
      containers:
        - name: app
          image: nginx:1.25
          env:
            - name: DATABASE_URL
              value: postgres://localhost/db
            - name: SECRET_KEY
              value: abc
          resources:
            limits:
              memory: 256Mi
              cpu: 500m
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
"""

MINIMAL_YAML = """
apiVersion: v1
kind: Pod
metadata:
  name: simple-pod
spec:
  containers:
    - name: app
      image: myimage:latest
"""


class TestParseManifest:
    def test_extracts_kind(self):
        result = parse_manifest(DEPLOYMENT_YAML)
        assert result["manifest_type"] == "Deployment"

    def test_extracts_name(self):
        result = parse_manifest(DEPLOYMENT_YAML)
        assert result["name"] == "my-app"

    def test_extracts_namespace(self):
        result = parse_manifest(DEPLOYMENT_YAML)
        assert result["namespace"] == "staging"

    def test_extracts_image(self):
        result = parse_manifest(DEPLOYMENT_YAML)
        assert result["image"] == "nginx:1.25"

    def test_extracts_env_vars(self):
        result = parse_manifest(DEPLOYMENT_YAML)
        assert "DATABASE_URL" in result["env_vars"]
        assert "SECRET_KEY" in result["env_vars"]

    def test_extracts_memory_limit(self):
        result = parse_manifest(DEPLOYMENT_YAML)
        assert result["memory_limit"] == "256Mi"

    def test_extracts_cpu_limit(self):
        result = parse_manifest(DEPLOYMENT_YAML)
        assert result["cpu_limit"] == "500m"

    def test_detects_liveness_probe(self):
        result = parse_manifest(DEPLOYMENT_YAML)
        assert result["has_liveness_probe"] is True

    def test_detects_readiness_probe(self):
        result = parse_manifest(DEPLOYMENT_YAML)
        assert result["has_readiness_probe"] is True

    def test_raw_config_is_non_empty_string(self):
        result = parse_manifest(DEPLOYMENT_YAML)
        assert isinstance(result["raw_config"], str)
        assert len(result["raw_config"]) > 0

    def test_latest_tag_is_not_fixed(self):
        result = parse_manifest(MINIMAL_YAML)
        assert result["image_has_fixed_tag"] is False

    def test_fixed_tag_is_detected(self):
        result = parse_manifest(DEPLOYMENT_YAML)
        assert result["image_has_fixed_tag"] is True

    def test_pod_spec_containers_are_found(self):
        result = parse_manifest(MINIMAL_YAML)
        assert result["name"] == "simple-pod"
        assert result["image"] == "myimage:latest"

    def test_namespace_defaults_to_default_when_absent(self):
        result = parse_manifest(MINIMAL_YAML)
        assert result["namespace"] == "default"

    def test_no_probes_when_absent(self):
        result = parse_manifest(MINIMAL_YAML)
        assert result["has_liveness_probe"] is False
        assert result["has_readiness_probe"] is False

    def test_no_limits_when_absent(self):
        result = parse_manifest(MINIMAL_YAML)
        assert result["memory_limit"] == ""
        assert result["cpu_limit"] == ""

    def test_invalid_yaml_returns_empty(self):
        result = parse_manifest("{ not: valid: yaml: }", manifest_type="Unknown")
        assert result["name"] == ""
        assert result["manifest_type"] == "Unknown"

    def test_non_dict_yaml_returns_empty(self):
        result = parse_manifest("- item1\n- item2")
        assert result["name"] == ""

    def test_empty_string_returns_empty(self):
        result = parse_manifest("")
        assert result["name"] == ""

    def test_image_without_tag_is_not_fixed(self):
        yaml_content = """
apiVersion: v1
kind: Pod
metadata:
  name: no-tag-pod
spec:
  containers:
    - name: app
      image: myimage
"""
        result = parse_manifest(yaml_content)
        assert result["image_has_fixed_tag"] is False
