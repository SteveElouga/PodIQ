import strawberry


@strawberry.type
class AnalysisResultType:
    error_type: str
    root_cause: str
    explanation: str
    solution: str
    confidence: str
    is_recurring: bool
    recurrence_count: int
    correlated_service: str | None
    correlation_explanation: str | None


@strawberry.type
class RiskItemType:
    severity: str
    category: str
    description: str
    fix: str


@strawberry.type
class ManifestScanResultType:
    risk_level: str
    summary: str
    risks: list[RiskItemType]


@strawberry.type
class AnalysisHistoryItem:
    id: str
    pod_name: str
    namespace: str
    error_type: str
    root_cause: str
    solution: str
    confidence: str
    is_recurring: bool
    recurrence_count: int
    created_at: str


@strawberry.type
class AnalysisJobType:
    job_id: strawberry.ID
    status: str  # pending | running | complete | failed
    result: AnalysisResultType | None
    error: str | None
    created_at: str


@strawberry.type
class AuthPayload:
    token: str
    user_id: str
    email: str
