import uuid

from django.db import models


class AnalysisType(models.TextChoices):
    INCIDENT = "incident", "Incident"
    PREDEPLOY = "predeploy", "Pre-deploy"
    CICD = "cicd", "CI/CD"


class ConfidenceLevel(models.TextChoices):
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class RiskLevel(models.TextChoices):
    SAFE = "safe", "Safe"
    WARNING = "warning", "Warning"
    BLOCK = "block", "Block"


class Analysis(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Référence applicative vers auth-service — pas de FK cross-service
    user_id = models.UUIDField()
    analysis_type = models.CharField(max_length=20, choices=AnalysisType.choices)
    pod_name = models.CharField(max_length=255, blank=True)
    namespace = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=100, blank=True)
    error_type = models.CharField(max_length=255, blank=True)
    root_cause = models.TextField(blank=True)
    explanation = models.TextField(blank=True)
    solution = models.TextField(blank=True)
    confidence = models.CharField(
        max_length=20, choices=ConfidenceLevel.choices, blank=True
    )
    risk_level = models.CharField(max_length=20, choices=RiskLevel.choices, blank=True)
    is_recurring = models.BooleanField(default=False)
    recurrence_count = models.IntegerField(default=0)
    correlated_service = models.CharField(max_length=255, blank=True)
    correlation_type = models.CharField(max_length=50, blank=True)
    risks = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "analyses"
        indexes = [
            models.Index(fields=["pod_name", "namespace"], name="analyses_pod_ns_idx"),
            models.Index(fields=["created_at"], name="analyses_created_idx"),
            models.Index(fields=["user_id"], name="analyses_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.analysis_type}:{self.pod_name}/{self.namespace}"


class IncidentPattern(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pod_name = models.CharField(max_length=255)
    namespace = models.CharField(max_length=255)
    error_type = models.CharField(max_length=255)
    occurrence_count = models.IntegerField(default=1)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    last_solution = models.TextField(blank=True)

    class Meta:
        db_table = "incident_patterns"
        unique_together = [("pod_name", "namespace", "error_type")]
        indexes = [
            models.Index(fields=["pod_name", "namespace"], name="patterns_pod_ns_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.pod_name}/{self.namespace}:{self.error_type}"
