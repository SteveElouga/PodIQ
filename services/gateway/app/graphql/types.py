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
    analysis_type: str
    risk_level: str


@strawberry.type
class ApiKeyPayload:
    key_id: str
    raw_key: str
    name: str
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


@strawberry.type
class WorkspaceAuthPayload:
    token: str
    user_id: str
    email: str
    workspace_id: str
    role: str


@strawberry.type
class WorkspaceType:
    id: str
    name: str
    slug: str
    plan: str
    role: str
    region: str
    team_size: str
    accent_color: str
    onboarded_at: str | None
    created_at: str


@strawberry.type
class InstallTokenPayload:
    token: str
    workspace_id: str
    expires_at: str


@strawberry.type
class ClusterType:
    id: str
    name: str
    k8s_version: str
    status: str
    workspace_id: str
    last_heartbeat: str | None
    created_at: str
