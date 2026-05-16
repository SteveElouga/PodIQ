import os
from typing import Any

import structlog
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from app.parsers import log_cleaner

logger = structlog.get_logger()

STUB_MODE = os.environ.get("STUB_MODE", "false").lower() == "true"


def _load_k8s_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def _stub_collect_pod(pod_name: str, namespace: str) -> dict[str, Any]:
    logger.info("collect_pod_stub", pod=pod_name, namespace=namespace)
    return {
        "pod_name": pod_name,
        "namespace": namespace,
        "status": "CrashLoopBackOff",
        "logs": (
            "ERROR: Failed to connect to database: connection refused (host=postgres, port=5432)\n"
            "ERROR: Retrying in 5s... (attempt 1/5)\n"
            "ERROR: Retrying in 5s... (attempt 2/5)\n"
            "ERROR: Retrying in 5s... (attempt 3/5)\n"
            "FATAL: Max retries exceeded. Exiting.\n"
        ),
        "events": (
            "2026-05-11T08:00:00Z  [Warning]  BackOff: Back-off restarting failed container\n"
            "2026-05-11T08:00:10Z  [Warning]  Failed: Error: failed to start container: "
            "exec: no such file or directory\n"
        ),
        "describe_output": (
            f"Name:       {pod_name}\n"
            f"Namespace:  {namespace}\n"
            "Status:     CrashLoopBackOff\n"
            "Node:       minikube\n\n"
            "Container: app\n"
            "  Ready:         False\n"
            "  Restart Count: 7\n"
            "  State:         Waiting / CrashLoopBackOff\n"
            "  Message:       back-off 5m0s restarting failed container\n"
        ),
    }


def collect_pod(pod_name: str, namespace: str, log_lines: int = 2000) -> dict[str, Any]:
    if STUB_MODE:
        return _stub_collect_pod(pod_name, namespace)
    _load_k8s_config()
    v1 = client.CoreV1Api()

    logs = _collect_logs(v1, pod_name, namespace, log_lines)
    status, describe = _collect_describe(v1, pod_name, namespace)
    events = _collect_events(v1, pod_name, namespace)

    return {
        "pod_name": pod_name,
        "namespace": namespace,
        "status": status,
        "logs": log_cleaner.clean(logs),
        "events": log_cleaner.mask_secrets(events),
        "describe_output": log_cleaner.mask_secrets(describe),
    }


def _collect_logs(v1: client.CoreV1Api, pod_name: str, namespace: str, log_lines: int) -> str:
    try:
        return v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=min(log_lines, log_cleaner.MAX_LOG_LINES),
        )
    except ApiException as e:
        logger.warning("pod_logs_unavailable", pod=pod_name, namespace=namespace, status=e.status)
        return f"[logs unavailable: {e.reason}]"


def _collect_describe(v1: client.CoreV1Api, pod_name: str, namespace: str) -> tuple[str, str]:
    try:
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        return pod.status.phase or "Unknown", _format_describe(pod)
    except ApiException as e:
        logger.warning("pod_describe_unavailable", pod=pod_name, namespace=namespace, status=e.status)
        return "Unknown", f"[describe unavailable: {e.reason}]"


def _collect_events(v1: client.CoreV1Api, pod_name: str, namespace: str) -> str:
    try:
        event_list = v1.list_namespaced_event(
            namespace=namespace,
            field_selector=f"involvedObject.name={pod_name}",
        )
        return _format_events(event_list.items)
    except ApiException as e:
        logger.warning("pod_events_unavailable", pod=pod_name, namespace=namespace, status=e.status)
        return f"[events unavailable: {e.reason}]"


def _format_describe(pod: Any) -> str:
    lines = [
        f"Name:       {pod.metadata.name}",
        f"Namespace:  {pod.metadata.namespace}",
        f"Status:     {pod.status.phase}",
        f"Node:       {pod.spec.node_name or 'unknown'}",
    ]
    for cs in pod.status.container_statuses or []:
        lines.append(f"\nContainer: {cs.name}")
        lines.append(f"  Ready:         {cs.ready}")
        lines.append(f"  Restart Count: {cs.restart_count}")
        if cs.state.waiting:
            lines.append(f"  State:         Waiting / {cs.state.waiting.reason}")
            if cs.state.waiting.message:
                lines.append(f"  Message:       {cs.state.waiting.message}")
        elif cs.state.running:
            lines.append(f"  State:         Running since {cs.state.running.started_at}")
        elif cs.state.terminated:
            t = cs.state.terminated
            lines.append(f"  State:         Terminated / {t.reason} (exit {t.exit_code})")
    return "\n".join(lines)


def _format_events(events: list[Any]) -> str:
    if not events:
        return "No events."

    def sort_key(e: Any) -> Any:
        return e.last_timestamp or e.event_time or ""

    lines = []
    for e in sorted(events, key=sort_key):
        lines.append(f"{e.last_timestamp}  [{e.type}]  {e.reason}: {e.message}")
    return "\n".join(lines)
