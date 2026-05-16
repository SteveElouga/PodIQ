import uuid

from django.db import models


class User(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=255, unique=True)
    password_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users"

    def __str__(self) -> str:
        return self.email


class ApiKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Application-level reference (no cross-service FK)
    user_id = models.UUIDField()
    key_hash = models.CharField(max_length=255)
    name = models.CharField(max_length=100, blank=True)
    last_used = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "api_keys"
        indexes = [
            models.Index(fields=["user_id"], name="apikey_user_idx"),
            models.Index(fields=["key_hash"], name="apikey_hash_idx"),
        ]

    def __str__(self) -> str:
        return self.name or str(self.id)
