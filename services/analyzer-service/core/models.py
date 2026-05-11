import uuid

from django.db import models


class LogsSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Référence applicative vers ai-service — pas de FK cross-service
    analysis_id = models.UUIDField()
    raw_logs = models.TextField(blank=True)
    events = models.TextField(blank=True)
    describe_output = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "logs_snapshots"
        indexes = [
            models.Index(fields=["analysis_id"], name="logs_analysis_idx"),
        ]

    def __str__(self) -> str:
        return f"logs:{self.analysis_id}"


class NamespaceSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Référence applicative vers ai-service — pas de FK cross-service
    analysis_id = models.UUIDField()
    namespace = models.CharField(max_length=255)
    pods_state = models.JSONField()
    collected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "namespace_snapshots"
        indexes = [
            models.Index(fields=["analysis_id"], name="ns_analysis_idx"),
            models.Index(fields=["namespace", "collected_at"], name="ns_namespace_time_idx"),
        ]

    def __str__(self) -> str:
        return f"namespace:{self.namespace}:{self.analysis_id}"
