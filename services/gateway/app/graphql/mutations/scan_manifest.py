from functools import partial

import grpc
import strawberry
import structlog
from strawberry.types import Info

from app.auth import require_auth
from app.graphql.types import ManifestScanResultType, RiskItemType
from app.grpc_clients import ai_client, analyzer_client
from app.grpc_errors import GrpcService, invoke_grpc
from stubs.ai import ai_pb2

logger = structlog.get_logger()


def _fetch_history(manifest_name: str, namespace: str) -> list[ai_pb2.PastIncident]:
    try:
        response = ai_client.get_history(
            pod_name=manifest_name,
            namespace=namespace,
            limit=5,
        )
        return [
            ai_pb2.PastIncident(
                error_type=item.error_type,
                root_cause=item.root_cause,
                solution=item.solution,
                occurred_at=item.created_at,
            )
            for item in response.items
        ]
    except grpc.RpcError:
        logger.warning(
            "manifest_history_unavailable", manifest=manifest_name, namespace=namespace
        )
        return []


def _scan_manifest(
    info: Info, yaml_content: str, manifest_type: str = ""
) -> ManifestScanResultType:
    user_id = require_auth(info)
    logger.info("mutation_scan_manifest", manifest_type=manifest_type, user_id=user_id)

    parsed = invoke_grpc(
        GrpcService.ANALYZER,
        partial(
            analyzer_client.parse_manifest,
            yaml_content=yaml_content,
            manifest_type=manifest_type,
        ),
    )

    history = _fetch_history(parsed.name, parsed.namespace)
    logger.info(
        "manifest_history_fetched",
        manifest=parsed.name,
        namespace=parsed.namespace,
        history_count=len(history),
    )

    result = invoke_grpc(
        GrpcService.AI,
        partial(
            ai_client.scan_manifest,
            parsed_manifest=parsed.raw_config,
            user_id=user_id,
            manifest_name=parsed.name,
            manifest_namespace=parsed.namespace,
            manifest_type=parsed.manifest_type,
            related_history=history,
        ),
    )

    return ManifestScanResultType(
        risk_level=result.risk_level,
        summary=result.summary,
        risks=[
            RiskItemType(
                severity=r.severity,
                category=r.category,
                description=r.description,
                fix=r.fix,
            )
            for r in result.risks
        ],
    )


@strawberry.mutation
def scan_manifest(
    info: Info, yaml_content: str, manifest_type: str = ""
) -> ManifestScanResultType:
    return _scan_manifest(info, yaml_content, manifest_type)
