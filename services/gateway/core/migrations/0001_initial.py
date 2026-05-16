import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies: list = []

    operations = [
        migrations.CreateModel(
            name="AnalysisJob",
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
                ("user_id", models.UUIDField()),
                ("pod_name", models.CharField(max_length=253)),
                ("namespace", models.CharField(max_length=253)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("complete", "Complete"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=10,
                    ),
                ),
                ("result", models.JSONField(blank=True, null=True)),
                ("error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "analysis_jobs"},
        ),
        migrations.AddIndex(
            model_name="analysisjob",
            index=models.Index(fields=["user_id", "-created_at"], name="job_user_idx"),
        ),
        migrations.AddIndex(
            model_name="analysisjob",
            index=models.Index(fields=["status"], name="job_status_idx"),
        ),
    ]
