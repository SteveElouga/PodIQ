import grpc
from django.conf import settings

from stubs.analyzer import analyzer_pb2, analyzer_pb2_grpc


def _channel() -> grpc.Channel:
    return grpc.insecure_channel(
        f"{settings.ANALYZER_GRPC_HOST}:{settings.ANALYZER_GRPC_PORT}"
    )


def collect_pod(pod_name: str, namespace: str, log_lines: int = 2000) -> analyzer_pb2.PodData:
    with _channel() as channel:
        stub = analyzer_pb2_grpc.AnalyzerServiceStub(channel)
        return stub.CollectPod(
            analyzer_pb2.PodRequest(
                pod_name=pod_name,
                namespace=namespace,
                log_lines=log_lines,
            )
        )


def scan_namespace(namespace: str, timestamp: int = 0) -> analyzer_pb2.NamespaceSnapshot:
    with _channel() as channel:
        stub = analyzer_pb2_grpc.AnalyzerServiceStub(channel)
        return stub.ScanNamespace(
            analyzer_pb2.NamespaceRequest(
                namespace=namespace,
                timestamp=timestamp,
            )
        )


def parse_manifest(yaml_content: str, manifest_type: str = "") -> analyzer_pb2.ParsedManifest:
    with _channel() as channel:
        stub = analyzer_pb2_grpc.AnalyzerServiceStub(channel)
        return stub.ParseManifest(
            analyzer_pb2.ManifestRequest(
                yaml_content=yaml_content,
                manifest_type=manifest_type,
            )
        )
