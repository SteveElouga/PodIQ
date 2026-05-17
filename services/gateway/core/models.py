import uuid

from django.db import models


class AnalysisJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        RUNNING = "running"
        COMPLETE = "complete"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField()  # cross-service reference, no FK
    pod_name = models.CharField(max_length=253)
    namespace = models.CharField(max_length=253)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "analysis_jobs"
        indexes = [
            models.Index(fields=["user_id", "-created_at"], name="job_user_idx"),
            models.Index(fields=["status"], name="job_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.pod_name}/{self.namespace} [{self.status}]"
