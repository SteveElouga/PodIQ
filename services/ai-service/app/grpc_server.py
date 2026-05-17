import json
import os
import sys
import uuid
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
from django.db.models import Count
from pydantic import ValidationError

from app.ollama.client import chat
from app.prompts import incident_prompt, predeploy_prompt
from app.schemas.analysis import AnalysisResponse
from app.schemas.predeploy import ManifestScanResponse
from core.models import Analysis, IncidentPattern
from stubs.ai import ai_pb2, ai_pb2_grpc

logger = structlog.get_logger()


class AIServicer(ai_pb2_grpc.AIServiceServicer):

    def AnalyzeIncident(
        self,
        request: ai_pb2.IncidentRequest,
        context: grpc.ServicerContext,
    ) -> ai_pb2.AnalysisResult:
        logger.info(
            "analyze_incident", pod=request.pod_name, namespace=request.namespace
        )

        try:
            prompt = incident_prompt.build(request)
            raw = chat(prompt=prompt, system=incident_prompt.SYSTEM)
            result = _parse_incident(raw)
        except Exception as exc:
            logger.error("analyze_incident_failed", error=str(exc))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(exc))
            return ai_pb2.AnalysisResult()

        _save_analysis(request, result)
        _upsert_pattern(request, result)
        recurrence_count = _get_recurrence_count(
            request.pod_name, request.namespace, result.error_type
        )

        return ai_pb2.AnalysisResult(
            error_type=result.error_type,
            root_cause=result.root_cause,
            explanation=result.explanation,
            solution=result.solution,
            confidence=result.confidence,
            is_recurring=result.is_recurring,
            recurrence_count=recurrence_count,
            correlated_service=result.correlated_service or "",
            correlation_explanation=result.correlation_explanation or "",
        )

    def GetAnalysisHistory(
        self,
        request: ai_pb2.HistoryRequest,
        context: grpc.ServicerContext,
    ) -> ai_pb2.HistoryResponse:
        logger.info(
            "get_analysis_history", pod=request.pod_name, namespace=request.namespace
        )

        filters: dict = {"pod_name": request.pod_name, "namespace": request.namespace}
        if request.analysis_type:
            filters["analysis_type"] = request.analysis_type
        qs = Analysis.objects.filter(**filters).order_by("-created_at")

        limit = request.limit if request.limit > 0 else 10
        page: list[Analysis] = list(qs[:limit])

        # Single aggregation query for all predeploy counts — avoids N+1
        predeploy_keys = {
            (a.pod_name, a.namespace, a.error_type)
            for a in page
            if a.analysis_type == "predeploy"
        }
        predeploy_counts: dict[tuple[str, str, str], int] = {}
        if predeploy_keys:
            rows = (
                Analysis.objects.filter(analysis_type="predeploy")
                .values("pod_name", "namespace", "error_type")
                .annotate(cnt=Count("id"))
            )
            predeploy_counts = {
                (r["pod_name"], r["namespace"], r["error_type"]): r["cnt"] for r in rows
            }

        items = []
        for a in page:
            if a.analysis_type == "predeploy":
                recurrence_count = predeploy_counts.get(
                    (a.pod_name, a.namespace, a.error_type), 1
                )
                is_recurring = recurrence_count > 1
            else:
                recurrence_count = _get_recurrence_count(
                    a.pod_name, a.namespace, a.error_type
                )
                is_recurring = a.is_recurring
            items.append(
                ai_pb2.HistoryItem(
                    id=str(a.id),
                    pod_name=a.pod_name,
                    namespace=a.namespace,
                    error_type=a.error_type,
                    root_cause=a.root_cause,
                    solution=a.solution,
                    confidence=a.confidence,
                    is_recurring=is_recurring,
                    recurrence_count=recurrence_count,
                    created_at=int(a.created_at.timestamp()),
                    analysis_type=a.analysis_type,
                    risk_level=a.risk_level or "",
                )
            )

        return ai_pb2.HistoryResponse(items=items)

    def ScanManifest(
        self,
        request: ai_pb2.ManifestScanRequest,
        context: grpc.ServicerContext,
    ) -> ai_pb2.ManifestScanResult:
        logger.info("scan_manifest")

        try:
            prompt = predeploy_prompt.build(request)
            raw = chat(prompt=prompt, system=predeploy_prompt.SYSTEM)
            result = _parse_scan(raw)
        except Exception as exc:
            logger.error("scan_manifest_failed", error=str(exc))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(exc))
            return ai_pb2.ManifestScanResult()

        _save_predeploy_analysis(request, result)
        _upsert_predeploy_pattern(request, result)
        logger.info(
            "scan_manifest_complete",
            manifest=request.manifest_name,
            namespace=request.manifest_namespace,
            risk_level=result.risk_level,
        )

        risks = [
            ai_pb2.RiskItem(
                severity=r.severity,
                category=r.category,
                description=r.description,
                fix=r.fix,
            )
            for r in result.risks
        ]

        return ai_pb2.ManifestScanResult(
            risk_level=result.risk_level,
            risks=risks,
            summary=result.summary,
        )


# ── Parsing ───────────────────────────────────────────────────────────────────


def _extract_json(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]
    return raw


def _parse_incident(raw: str) -> AnalysisResponse:
    try:
        return AnalysisResponse.model_validate(json.loads(_extract_json(raw)))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("incident_parse_failed", error=str(exc), raw_preview=raw[:200])
        return AnalysisResponse(
            error_type="Unknown",
            root_cause="AI response could not be parsed.",
            explanation=raw[:500] if raw else "Empty response.",
            solution="Retry the analysis or inspect the pod manually.",
            confidence="low",
            is_recurring=False,
        )


def _parse_scan(raw: str) -> ManifestScanResponse:
    try:
        return ManifestScanResponse.model_validate(json.loads(_extract_json(raw)))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("scan_parse_failed", error=str(exc), raw_preview=raw[:200])
        return ManifestScanResponse(
            risk_level="warning",
            summary="AI response could not be parsed.",
            risks=[],
        )


# ── Persistence ───────────────────────────────────────────────────────────────


def _save_predeploy_analysis(
    request: ai_pb2.ManifestScanRequest, result: ManifestScanResponse
) -> None:
    try:
        user_uuid = uuid.UUID(request.user_id)
    except (ValueError, AttributeError):
        logger.warning("predeploy_invalid_user_id", user_id=request.user_id)
        return
    _RISK_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_risks = sorted(
        result.risks, key=lambda r: _RISK_SEVERITY_ORDER.get(r.severity, 99)
    )
    top_risk = sorted_risks[0] if sorted_risks else None

    error_type = top_risk.category if top_risk else result.risk_level
    root_cause = "\n".join(
        f"[{r.severity.upper()}] {r.description}" for r in sorted_risks if r.description
    )
    solution = "\n".join(
        f"[{r.severity.upper()}] {r.fix}" for r in sorted_risks if r.fix
    )
    confidence_map = {"block": "high", "warning": "medium", "safe": "low"}
    confidence = confidence_map.get(result.risk_level, "low")

    # Check for existing pattern before saving so is_recurring is accurate
    is_recurring = (
        IncidentPattern.objects.filter(
            pod_name=request.manifest_name,
            namespace=request.manifest_namespace,
            error_type=error_type,
        ).exists()
        if request.manifest_name and error_type
        else False
    )

    Analysis.objects.create(
        user_id=user_uuid,
        analysis_type="predeploy",
        pod_name=request.manifest_name,
        namespace=request.manifest_namespace,
        error_type=error_type,
        root_cause=root_cause,
        explanation=result.summary,
        solution=solution,
        confidence=confidence,
        is_recurring=is_recurring,
        risk_level=result.risk_level,
        risks=[
            {
                "severity": r.severity,
                "category": r.category,
                "description": r.description,
                "fix": r.fix,
            }
            for r in sorted_risks
        ],
    )


def _save_analysis(
    request: ai_pb2.IncidentRequest, result: AnalysisResponse
) -> Analysis:
    risks = [
        {
            "severity": result.confidence,
            "category": result.error_type,
            "description": result.root_cause,
            "fix": result.solution,
        }
    ]
    if result.correlated_service:
        risks.append(
            {
                "severity": "medium",
                "category": "correlation",
                "description": result.correlation_explanation or "",
                "fix": f"Investigate {result.correlated_service}",
            }
        )
    return Analysis.objects.create(
        user_id=uuid.uuid4(),  # replaced by gateway-provided user_id in full flow
        analysis_type="incident",
        pod_name=request.pod_name,
        namespace=request.namespace,
        status=request.status,
        error_type=result.error_type,
        root_cause=result.root_cause,
        explanation=result.explanation,
        solution=result.solution,
        confidence=result.confidence,
        is_recurring=result.is_recurring,
        correlated_service=result.correlated_service or "",
        risks=risks,
    )


def _upsert_pattern(request: ai_pb2.IncidentRequest, result: AnalysisResponse) -> None:
    if not request.pod_name:
        return
    obj, created = IncidentPattern.objects.get_or_create(
        pod_name=request.pod_name,
        namespace=request.namespace,
        error_type=result.error_type,
        defaults={"last_solution": result.solution},
    )
    if not created:
        obj.occurrence_count += 1
        obj.last_solution = result.solution
        obj.save(update_fields=["occurrence_count", "last_solution", "last_seen"])


def _upsert_predeploy_pattern(
    request: ai_pb2.ManifestScanRequest, result: ManifestScanResponse
) -> None:
    if not request.manifest_name:
        return
    _RISK_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_risks = sorted(
        result.risks, key=lambda r: _RISK_SEVERITY_ORDER.get(r.severity, 99)
    )
    top_risk = sorted_risks[0] if sorted_risks else None
    error_type = top_risk.category if top_risk else result.risk_level
    solution = "; ".join(r.fix for r in sorted_risks if r.fix)[:500]

    obj, created = IncidentPattern.objects.get_or_create(
        pod_name=request.manifest_name,
        namespace=request.manifest_namespace,
        error_type=error_type,
        defaults={"last_solution": solution},
    )
    if not created:
        obj.occurrence_count += 1
        obj.last_solution = solution
        obj.save(update_fields=["occurrence_count", "last_solution", "last_seen"])


def _get_recurrence_count(pod_name: str, namespace: str, error_type: str) -> int:
    try:
        return IncidentPattern.objects.get(
            pod_name=pod_name,
            namespace=namespace,
            error_type=error_type,
        ).occurrence_count
    except IncidentPattern.DoesNotExist:
        return 0


# ── Entrypoint ────────────────────────────────────────────────────────────────


def serve() -> None:
    port = os.environ.get("GRPC_PORT", "50053")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    ai_pb2_grpc.add_AIServiceServicer_to_server(AIServicer(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info("ai_service_started", port=port)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("ai_service_stopping")
        server.stop(grace=5)


if __name__ == "__main__":
    serve()
