import os
import time
from typing import Any

import structlog
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

logger = structlog.get_logger()

_ERROR_REASONS = {
    "CrashLoopBackOff",
    "OOMKilled",
    "Error",
    "ImagePullBackOff",
    "ErrImagePull",
}
STUB_MODE = os.environ.get("STUB_MODE", "false").lower() == "true"


def _load_k8s_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def _stub_scan_namespace(namespace: str, incident_timestamp: int) -> dict[str, Any]:
    now_ts = int(time.time())
    ref_ts = incident_timestamp if incident_timestamp > 0 else now_ts
    logger.info("scan_namespace_stub", namespace=namespace, incident_timestamp=ref_ts)
    return {
        "namespace": namespace,
        "pods": [
            {
                "pod_name": "api-gateway-7d9f",
                "status": "Running",
                "has_errors": False,
                "last_restart_time": 0,
            },
            {
                "pod_name": "worker-6b8c",
                "status": "CrashLoopBackOff",
                "has_errors": True,
                "last_restart_time": ref_ts - 300,
            },
            {
                "pod_name": "redis-0",
                "status": "Running",
                "has_errors": False,
                "last_restart_time": 0,
            },
        ],
        "collected_at": ref_ts,
    }


def scan_namespace(namespace: str, incident_timestamp: int = 0) -> dict[str, Any]:
    if STUB_MODE:
        return _stub_scan_namespace(namespace, incident_timestamp)
    _load_k8s_config()
    v1 = client.CoreV1Api()

    pods: list[dict[str, Any]] = []
    try:
        pod_list = v1.list_namespaced_pod(namespace=namespace)
        for pod in pod_list.items:
            pods.append(_summarize_pod(pod))
    except ApiException as e:
        logger.warning(
            "namespace_scan_failed",
            namespace=namespace,
            status=e.status,
            reason=e.reason,
        )

    collected_at = int(time.time())
    logger.info(
        "namespace_scan_complete",
        namespace=namespace,
        pod_count=len(pods),
        incident_timestamp=incident_timestamp,
        collected_at=collected_at,
    )
    return {
        "namespace": namespace,
        "pods": pods,
        "collected_at": collected_at,
    }


def _summarize_pod(pod: Any) -> dict[str, Any]:
    phase = pod.status.phase or "Unknown"
    has_errors = phase not in ("Running", "Succeeded")
    last_restart_time = 0

    for cs in pod.status.container_statuses or []:
        if cs.restart_count > 0:
            has_errors = True
        if cs.state.waiting and cs.state.waiting.reason in _ERROR_REASONS:
            has_errors = True
        if cs.last_state.terminated and cs.last_state.terminated.finished_at:
            ts = int(cs.last_state.terminated.finished_at.timestamp())
            last_restart_time = max(last_restart_time, ts)

    return {
        "pod_name": pod.metadata.name,
        "status": phase,
        "has_errors": has_errors,
        "last_restart_time": last_restart_time,
    }
