from typing import Any

import structlog
import yaml

logger = structlog.get_logger()

# Image tags without a pinned version are risky in production
_UNSAFE_TAGS = {"latest", ""}


def parse_manifest(yaml_content: str, manifest_type: str = "") -> dict[str, Any]:
    try:
        doc = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        logger.warning("yaml_parse_error", error=str(e))
        return _empty(manifest_type)

    if not isinstance(doc, dict):
        return _empty(manifest_type)

    kind = doc.get("kind", manifest_type or "Unknown")
    metadata = doc.get("metadata", {})
    name = metadata.get("name", "")
    namespace = metadata.get("namespace", "default")

    container = _extract_main_container(doc)
    image = container.get("image", "")

    return {
        "manifest_type": kind,
        "name": name,
        "namespace": namespace,
        "env_vars": _extract_env_names(container),
        "memory_limit": _get_resource(container, "limits", "memory"),
        "cpu_limit": _get_resource(container, "limits", "cpu"),
        "has_liveness_probe": "livenessProbe" in container,
        "has_readiness_probe": "readinessProbe" in container,
        "image": image,
        "image_has_fixed_tag": _has_fixed_tag(image),
        "raw_config": _safe_dump(doc),
    }


def _extract_main_container(doc: dict[str, Any]) -> dict[str, Any]:
    spec = doc.get("spec", {})
    # Deployment / StatefulSet / DaemonSet ont un template
    template_spec = spec.get("template", {}).get("spec", {})
    containers = template_spec.get("containers") or spec.get("containers", [])
    return containers[0] if containers else {}


def _extract_env_names(container: dict[str, Any]) -> list[str]:
    return [
        e["name"]
        for e in container.get("env", [])
        if isinstance(e, dict) and "name" in e
    ]


def _get_resource(container: dict[str, Any], kind: str, unit: str) -> str:
    return container.get("resources", {}).get(kind, {}).get(unit, "")


def _has_fixed_tag(image: str) -> bool:
    if not image or ":" not in image:
        return False
    tag = image.rsplit(":", 1)[-1]
    return tag not in _UNSAFE_TAGS


def _safe_dump(doc: Any) -> str:
    try:
        return yaml.dump(doc, default_flow_style=False, allow_unicode=True)
    except Exception:
        return str(doc)


def _empty(manifest_type: str) -> dict[str, Any]:
    return {
        "manifest_type": manifest_type,
        "name": "",
        "namespace": "",
        "env_vars": [],
        "memory_limit": "",
        "cpu_limit": "",
        "has_liveness_probe": False,
        "has_readiness_probe": False,
        "image": "",
        "image_has_fixed_tag": False,
        "raw_config": "",
    }
