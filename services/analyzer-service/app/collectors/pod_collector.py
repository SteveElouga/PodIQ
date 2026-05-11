from typing import Any

import structlog
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from app.parsers import log_cleaner

logger = structlog.get_logger()


def _load_k8s_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def collect_pod(pod_name: str, namespace: str, log_lines: int = 2000) -> dict[str, Any]:
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
