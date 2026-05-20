import grpc
from django.conf import settings

from stubs.analyzer import analyzer_pb2, analyzer_pb2_grpc


def _channel() -> grpc.Channel:
    return grpc.insecure_channel(
        f"{settings.ANALYZER_GRPC_HOST}:{settings.ANALYZER_GRPC_PORT}"
    )


def parse_manifest(
    yaml_content: str, manifest_type: str = ""
) -> analyzer_pb2.ParsedManifest:
    with _channel() as channel:
        stub = analyzer_pb2_grpc.AnalyzerServiceStub(channel)
        return stub.ParseManifest(
            analyzer_pb2.ManifestRequest(
                yaml_content=yaml_content,
                manifest_type=manifest_type,
            )
        )
