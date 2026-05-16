import os
import time
from typing import Any

import structlog
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

logger = structlog.get_logger()

_ERROR_REASONS = {"CrashLoopBackOff", "OOMKilled", "Error", "ImagePullBackOff", "ErrImagePull"}
STUB_MODE = os.environ.get("STUB_MODE", "false").lower() == "true"


def _load_k8s_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def _stub_scan_namespace(namespace: str) -> dict[str, Any]:
    logger.info("scan_namespace_stub", namespace=namespace)
    return {
        "namespace": namespace,
        "pods": [
            {"pod_name": "api-gateway-7d9f", "status": "Running", "has_errors": False, "last_restart_time": 0},
            {"pod_name": "worker-6b8c", "status": "CrashLoopBackOff", "has_errors": True, "last_restart_time": int(time.time()) - 300},
            {"pod_name": "redis-0", "status": "Running", "has_errors": False, "last_restart_time": 0},
        ],
        "collected_at": int(time.time()),
    }


def scan_namespace(namespace: str) -> dict[str, Any]:
    if STUB_MODE:
        return _stub_scan_namespace(namespace)
    _load_k8s_config()
    v1 = client.CoreV1Api()

    pods: list[dict[str, Any]] = []
    try:
        pod_list = v1.list_namespaced_pod(namespace=namespace)
        for pod in pod_list.items:
            pods.append(_summarize_pod(pod))
    except ApiException as e:
        logger.warning("namespace_scan_failed", namespace=namespace, status=e.status, reason=e.reason)

    return {
        "namespace": namespace,
        "pods": pods,
        "collected_at": int(time.time()),
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
