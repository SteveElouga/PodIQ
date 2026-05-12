from django.conf import settings

from stubs.ai import ai_pb2
from stubs.analyzer import analyzer_pb2


def build_namespace_context(
    snapshot: analyzer_pb2.NamespaceSnapshot,
    target_pod_name: str,
) -> list[ai_pb2.PodContext]:
    window_sec = int(settings.CORRELATION_WINDOW_SECONDS)
    reference_ts = int(snapshot.collected_at) if snapshot.collected_at else 0
    if reference_ts <= 0:
        reference_ts = 0

    scored: list[tuple[bool, bool, str, ai_pb2.PodContext]] = []
    for p in snapshot.pods:
        if p.pod_name == target_pod_name:
            continue
        in_window = False
        seconds_before = 0
        if (
            reference_ts > 0
            and p.last_restart_time > 0
            and reference_ts >= p.last_restart_time
        ):
            delta = reference_ts - p.last_restart_time
            if delta <= window_sec:
                in_window = True
                seconds_before = int(delta)

        scored.append(
            (
                in_window,
                p.has_errors,
                p.pod_name,
                ai_pb2.PodContext(
                    pod_name=p.pod_name,
                    status=p.status,
                    had_issues=p.has_errors,
                    issue_timestamp=p.last_restart_time,
                    in_correlation_window=in_window,
                    seconds_before_reference=seconds_before,
                ),
            )
        )

    scored.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return [row[3] for row in scored]
