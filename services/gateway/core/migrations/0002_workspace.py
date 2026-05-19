import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        # ── Workspace ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Workspace",
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
                ("owner_id", models.UUIDField()),
                ("name", models.CharField(max_length=32)),
                ("slug", models.CharField(max_length=32, unique=True)),
                ("icon_url", models.URLField(blank=True, default="")),
                ("accent_color", models.CharField(default="#6366f1", max_length=7)),
                (
                    "team_size",
                    models.CharField(
                        choices=[
                            ("solo", "Solo"),
                            ("2_10", "Small"),
                            ("11_50", "Medium"),
                            ("50_plus", "Large"),
                        ],
                        default="solo",
                        max_length=10,
                    ),
                ),
                (
                    "region",
                    models.CharField(
                        choices=[("eu", "Eu"), ("us", "Us"), ("ap", "Ap")],
                        default="eu",
                        max_length=2,
                    ),
                ),
                (
                    "plan",
                    models.CharField(
                        choices=[
                            ("free", "Free"),
                            ("pro", "Pro"),
                            ("enterprise", "Enterprise"),
                        ],
                        default="free",
                        max_length=10,
                    ),
                ),
                ("onboarded_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "workspaces"},
        ),
        migrations.AddIndex(
            model_name="workspace",
            index=models.Index(fields=["owner_id"], name="ws_owner_idx"),
        ),
        migrations.AddIndex(
            model_name="workspace",
            index=models.Index(fields=["slug"], name="ws_slug_idx"),
        ),
        # ── WorkspaceMember ───────────────────────────────────────────────────
        migrations.CreateModel(
            name="WorkspaceMember",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="members",
                        to="core.workspace",
                    ),
                ),
                ("user_id", models.UUIDField()),
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
                ("joined_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "workspace_members"},
        ),
        migrations.AddConstraint(
            model_name="workspacemember",
            constraint=models.UniqueConstraint(
                fields=["workspace", "user_id"], name="unique_workspace_member"
            ),
        ),
        migrations.AddIndex(
            model_name="workspacemember",
            index=models.Index(fields=["user_id"], name="wsmember_user_idx"),
        ),
        # ── InstallToken ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name="InstallToken",
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
                        related_name="install_tokens",
                        to="core.workspace",
                    ),
                ),
                ("token", models.CharField(editable=False, max_length=64, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("used", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "install_tokens"},
        ),
        migrations.AddIndex(
            model_name="installtoken",
            index=models.Index(fields=["token"], name="installtoken_token_idx"),
        ),
        # ── Cluster ───────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Cluster",
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
                        related_name="clusters",
                        to="core.workspace",
                    ),
                ),
                (
                    "install_token",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="cluster",
                        to="core.installtoken",
                    ),
                ),
                ("name", models.CharField(max_length=253)),
                (
                    "k8s_version",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("connected", "Connected"),
                            ("disconnected", "Disconnected"),
                        ],
                        default="pending",
                        max_length=15,
                    ),
                ),
                ("last_heartbeat", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "clusters"},
        ),
        migrations.AddIndex(
            model_name="cluster",
            index=models.Index(
                fields=["workspace", "status"], name="cluster_ws_status_idx"
            ),
        ),
        # ── AnalysisJob — ajout workspace_id ─────────────────────────────────
        migrations.AddField(
            model_name="analysisjob",
            name="workspace_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
