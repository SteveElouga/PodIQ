import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_workspace"),
    ]

    operations = [
        # ── Invitation ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Invitation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invitations",
                        to="core.workspace",
                    ),
                ),
                ("email", models.EmailField(max_length=254)),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("admin", "Admin"),
                            ("member", "Member"),
                            ("viewer", "Viewer"),
                        ],
                        default="member",
                        max_length=10,
                    ),
                ),
                (
                    "token",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("accepted", "Accepted"),
                            ("revoked", "Revoked"),
                            ("expired", "Expired"),
                        ],
                        default="pending",
                        max_length=10,
                    ),
                ),
                ("invited_by_user_id", models.UUIDField()),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "invitations"},
        ),
        migrations.AddIndex(
            model_name="invitation",
            index=models.Index(fields=["token"], name="invitation_token_idx"),
        ),
        migrations.AddIndex(
            model_name="invitation",
            index=models.Index(
                fields=["workspace", "email"], name="invitation_ws_email_idx"
            ),
        ),
        # ── AlertRule ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="AlertRule",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="alert_rules",
                        to="core.workspace",
                    ),
                ),
                ("name", models.CharField(max_length=64)),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("crashloop", "Crashloop"),
                            ("oom", "Oom"),
                            ("predeploy_block", "Predeploy Block"),
                            ("fix_found", "Fix Found"),
                        ],
                        max_length=20,
                    ),
                ),
                ("enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "alert_rules"},
        ),
        migrations.AddIndex(
            model_name="alertrule",
            index=models.Index(
                fields=["workspace", "event_type"], name="alert_ws_type_idx"
            ),
        ),
        # ── NotificationChannel ───────────────────────────────────────────────
        migrations.CreateModel(
            name="NotificationChannel",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_channels",
                        to="core.workspace",
                    ),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("slack", "Slack"),
                            ("pagerduty", "Pagerduty"),
                            ("email", "Email"),
                            ("webhook", "Webhook"),
                            ("teams", "Teams"),
                            ("discord", "Discord"),
                        ],
                        max_length=15,
                    ),
                ),
                ("config", models.JSONField(default=dict)),
                ("enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "notification_channels"},
        ),
        migrations.AddIndex(
            model_name="notificationchannel",
            index=models.Index(
                fields=["workspace", "type"], name="channel_ws_type_idx"
            ),
        ),
        # ── QuietHours ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="QuietHours",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "workspace",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="quiet_hours",
                        to="core.workspace",
                    ),
                ),
                ("enabled", models.BooleanField(default=False)),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                ("timezone", models.CharField(default="UTC", max_length=64)),
                ("weekdays_only", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "quiet_hours"},
        ),
    ]
