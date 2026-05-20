import os
import sys
from concurrent import futures
from pathlib import Path

_docker_setup = Path("/app/structlog_setup.py")
if _docker_setup.is_file():
    _root_app = str(_docker_setup.parent)
    if _root_app not in sys.path:
        sys.path.insert(0, _root_app)
else:
    for _ancestor in Path(__file__).resolve().parents:
        _candidate = _ancestor / "shared" / "podiq_logging" / "structlog_setup.py"
        if _candidate.is_file():
            _pkg = str(_candidate.parent)
            if _pkg not in sys.path:
                sys.path.insert(0, _pkg)
            break

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import grpc
import structlog

from app.parsers.yaml_parser import parse_manifest
from stubs.analyzer import analyzer_pb2, analyzer_pb2_grpc

logger = structlog.get_logger()


class AnalyzerServicer(analyzer_pb2_grpc.AnalyzerServiceServicer):

    def ParseManifest(
        self,
        request: analyzer_pb2.ManifestRequest,
        context: grpc.ServicerContext,
    ) -> analyzer_pb2.ParsedManifest:
        logger.info("parse_manifest", manifest_type=request.manifest_type)
        try:
            result = parse_manifest(
                yaml_content=request.yaml_content,
                manifest_type=request.manifest_type,
            )
        except Exception as exc:
            logger.error("parse_manifest_error", error=str(exc))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(exc))
            return analyzer_pb2.ParsedManifest()

        return analyzer_pb2.ParsedManifest(
            manifest_type=result["manifest_type"],
            name=result["name"],
            namespace=result["namespace"],
            env_vars=result["env_vars"],
            memory_limit=result["memory_limit"],
            cpu_limit=result["cpu_limit"],
            has_liveness_probe=result["has_liveness_probe"],
            has_readiness_probe=result["has_readiness_probe"],
            image=result["image"],
            image_has_fixed_tag=result["image_has_fixed_tag"],
            raw_config=result["raw_config"],
        )


def serve() -> None:
    port = os.environ.get("GRPC_PORT", "50052")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    analyzer_pb2_grpc.add_AnalyzerServiceServicer_to_server(AnalyzerServicer(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info("analyzer_service_started", port=port)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("analyzer_service_stopping")
        server.stop(grace=5)


if __name__ == "__main__":
    serve()
