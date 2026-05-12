from functools import partial


import strawberry
import structlog
from strawberry.types import Info

from app.graphql.types import ManifestScanResultType, RiskItemType
from app.grpc_clients import analyzer_client, ai_client
from app.auth import require_auth
from app.grpc_errors import GrpcService, invoke_grpc

logger = structlog.get_logger()


def _scan_manifest(info: Info, yaml_content: str, manifest_type: str = "") -> ManifestScanResultType:
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

    result = invoke_grpc(
        GrpcService.AI,
        partial(
            ai_client.scan_manifest,
            parsed_manifest=parsed.raw_config,
            related_history=[],
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
def scan_manifest(info: Info, yaml_content: str, manifest_type: str = "") -> ManifestScanResultType:
    return _scan_manifest(info, yaml_content, manifest_type)
