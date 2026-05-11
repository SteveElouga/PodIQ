import os
import sys
from concurrent import futures

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import grpc
import structlog

from stubs.analyzer import analyzer_pb2, analyzer_pb2_grpc
from app.collectors.pod_collector import collect_pod
from app.collectors.namespace_collector import scan_namespace
from app.parsers.yaml_parser import parse_manifest

logger = structlog.get_logger()


class AnalyzerServicer(analyzer_pb2_grpc.AnalyzerServiceServicer):

    def CollectPod(
        self,
        request: analyzer_pb2.PodRequest,
        context: grpc.ServicerContext,
    ) -> analyzer_pb2.PodData:
        logger.info("collect_pod", pod=request.pod_name, namespace=request.namespace)
        try:
            data = collect_pod(
                pod_name=request.pod_name,
                namespace=request.namespace,
                log_lines=request.log_lines or 2000,
            )
        except Exception as exc:
            logger.error("collect_pod_error", pod=request.pod_name, error=str(exc))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(exc))
            return analyzer_pb2.PodData()

        return analyzer_pb2.PodData(
            pod_name=data["pod_name"],
            namespace=data["namespace"],
            status=data["status"],
            logs=data["logs"],
            events=data["events"],
            describe_output=data["describe_output"],
        )

    def ScanNamespace(
        self,
        request: analyzer_pb2.NamespaceRequest,
        context: grpc.ServicerContext,
    ) -> analyzer_pb2.NamespaceSnapshot:
        logger.info("scan_namespace", namespace=request.namespace)
        try:
            result = scan_namespace(namespace=request.namespace)
        except Exception as exc:
            logger.error("scan_namespace_error", namespace=request.namespace, error=str(exc))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(exc))
            return analyzer_pb2.NamespaceSnapshot()

        pods = [
            analyzer_pb2.PodSummary(
                pod_name=p["pod_name"],
                status=p["status"],
                has_errors=p["has_errors"],
                last_restart_time=p["last_restart_time"],
            )
            for p in result["pods"]
        ]

        return analyzer_pb2.NamespaceSnapshot(
            namespace=result["namespace"],
            pods=pods,
            collected_at=result["collected_at"],
        )

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
