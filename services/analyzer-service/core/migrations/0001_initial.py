import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies: list = []

    operations = [
        migrations.CreateModel(
            name="LogsSnapshot",
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
                ("analysis_id", models.UUIDField()),
                ("raw_logs", models.TextField(blank=True)),
                ("events", models.TextField(blank=True)),
                ("describe_output", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "logs_snapshots"},
        ),
        migrations.CreateModel(
            name="NamespaceSnapshot",
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
                ("analysis_id", models.UUIDField()),
                ("namespace", models.CharField(max_length=255)),
                ("pods_state", models.JSONField()),
                ("collected_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "namespace_snapshots"},
        ),
        migrations.AddIndex(
            model_name="logssnapshot",
            index=models.Index(fields=["analysis_id"], name="logs_analysis_idx"),
        ),
        migrations.AddIndex(
            model_name="namespacesnapshot",
            index=models.Index(fields=["analysis_id"], name="ns_analysis_idx"),
        ),
        migrations.AddIndex(
            model_name="namespacesnapshot",
            index=models.Index(
                fields=["namespace", "collected_at"], name="ns_namespace_time_idx"
            ),
        ),
    ]
