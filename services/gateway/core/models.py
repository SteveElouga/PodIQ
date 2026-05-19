import secrets
import uuid

from django.db import models


class Workspace(models.Model):
    class Plan(models.TextChoices):
        FREE = "free"
        PRO = "pro"
        ENTERPRISE = "enterprise"

    class Region(models.TextChoices):
        EU = "eu"
        US = "us"
        AP = "ap"

    class TeamSize(models.TextChoices):
        SOLO = "solo"
        SMALL = "2_10"
        MEDIUM = "11_50"
        LARGE = "50_plus"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id = models.UUIDField()  # cross-service ref to auth User, no FK
    name = models.CharField(max_length=32)
    slug = models.CharField(max_length=32, unique=True)
    icon_url = models.URLField(blank=True, default="")
    accent_color = models.CharField(max_length=7, default="#6366f1")  # hex
    team_size = models.CharField(
        max_length=10, choices=TeamSize.choices, default=TeamSize.SOLO
    )
    region = models.CharField(max_length=2, choices=Region.choices, default=Region.EU)
    plan = models.CharField(max_length=10, choices=Plan.choices, default=Plan.FREE)
    onboarded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workspaces"
        indexes = [
            models.Index(fields=["owner_id"], name="ws_owner_idx"),
            models.Index(fields=["slug"], name="ws_slug_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


class WorkspaceMember(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin"
        MEMBER = "member"
        VIEWER = "viewer"

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="members"
    )
    user_id = models.UUIDField()  # cross-service ref to auth User, no FK
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workspace_members"
        unique_together = [("workspace", "user_id")]
        indexes = [
            models.Index(fields=["user_id"], name="wsmember_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.workspace.slug} [{self.role}]"


class InstallToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="install_tokens"
    )
    token = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "install_tokens"
        indexes = [
            models.Index(fields=["token"], name="installtoken_token_idx"),
        ]

    @staticmethod
    def generate_token() -> str:
        return f"wsk_{secrets.token_urlsafe(32)}"

    def __str__(self) -> str:
        return f"token for {self.workspace.slug}"


class Cluster(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        CONNECTED = "connected"
        DISCONNECTED = "disconnected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="clusters"
    )
    install_token = models.OneToOneField(
        InstallToken, on_delete=models.PROTECT, related_name="cluster"
    )
    name = models.CharField(max_length=253)
    k8s_version = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING
    )
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "clusters"
        indexes = [
            models.Index(fields=["workspace", "status"], name="cluster_ws_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.status}]"


class Invitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        REVOKED = "revoked"
        EXPIRED = "expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=10,
        choices=WorkspaceMember.Role.choices,
        default=WorkspaceMember.Role.MEMBER,
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    invited_by_user_id = models.UUIDField()  # cross-service ref, no FK
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "invitations"
        indexes = [
            models.Index(fields=["token"], name="invitation_token_idx"),
            models.Index(fields=["workspace", "email"], name="invitation_ws_email_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.email} → {self.workspace.slug} [{self.status}]"


class AlertRule(models.Model):
    class EventType(models.TextChoices):
        CRASHLOOP = "crashloop"
        OOM = "oom"
        PREDEPLOY_BLOCK = "predeploy_block"
        FIX_FOUND = "fix_found"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="alert_rules"
    )
    name = models.CharField(max_length=64)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "alert_rules"
        indexes = [
            models.Index(fields=["workspace", "event_type"], name="alert_ws_type_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} [{self.workspace.slug}]"


class NotificationChannel(models.Model):
    class ChannelType(models.TextChoices):
        SLACK = "slack"
        PAGERDUTY = "pagerduty"
        EMAIL = "email"
        WEBHOOK = "webhook"
        TEAMS = "teams"
        DISCORD = "discord"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="notification_channels"
    )
    type = models.CharField(max_length=15, choices=ChannelType.choices)
    config = models.JSONField(default=dict)  # webhook_url, routing_key, address, etc.
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_channels"
        indexes = [
            models.Index(fields=["workspace", "type"], name="channel_ws_type_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.type} @ {self.workspace.slug}"


class QuietHours(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        Workspace, on_delete=models.CASCADE, related_name="quiet_hours"
    )
    enabled = models.BooleanField(default=False)
    start_time = models.TimeField()  # local time in `timezone`
    end_time = models.TimeField()
    timezone = models.CharField(max_length=64, default="UTC")
    weekdays_only = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "quiet_hours"

    def __str__(self) -> str:
        return f"quiet {self.start_time}–{self.end_time} [{self.workspace.slug}]"


class AnalysisJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        RUNNING = "running"
        COMPLETE = "complete"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField()  # cross-service reference to auth User, no FK
    workspace_id = models.UUIDField(null=True, blank=True)  # cross-service ref, no FK
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
