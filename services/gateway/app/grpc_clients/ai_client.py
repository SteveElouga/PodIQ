import grpc
from django.conf import settings

from stubs.ai import ai_pb2, ai_pb2_grpc


def _channel() -> grpc.Channel:
    return grpc.insecure_channel(f"{settings.AI_GRPC_HOST}:{settings.AI_GRPC_PORT}")


def analyze_incident(
    pod_data: ai_pb2.IncidentRequest,
) -> ai_pb2.AnalysisResult:
    with _channel() as channel:
        stub = ai_pb2_grpc.AIServiceStub(channel)
        return stub.AnalyzeIncident(pod_data)


def scan_manifest(
    parsed_manifest: str,
    related_history: list[ai_pb2.PastIncident] | None = None,
) -> ai_pb2.ManifestScanResult:
    with _channel() as channel:
        stub = ai_pb2_grpc.AIServiceStub(channel)
        return stub.ScanManifest(
            ai_pb2.ManifestScanRequest(
                parsed_manifest=parsed_manifest,
                related_history=related_history or [],
            )
        )


def get_history(
    pod_name: str, namespace: str, limit: int = 10
) -> ai_pb2.HistoryResponse:
    with _channel() as channel:
        stub = ai_pb2_grpc.AIServiceStub(channel)
        return stub.GetAnalysisHistory(
            ai_pb2.HistoryRequest(
                pod_name=pod_name,
                namespace=namespace,
                limit=limit,
            )
        )
