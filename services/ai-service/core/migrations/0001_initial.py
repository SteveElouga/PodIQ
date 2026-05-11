import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies: list = []

    operations = [
        migrations.CreateModel(
            name="Analysis",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user_id", models.UUIDField()),
                ("analysis_type", models.CharField(choices=[("incident", "Incident"), ("predeploy", "Pre-deploy"), ("cicd", "CI/CD")], max_length=20)),
                ("pod_name", models.CharField(blank=True, max_length=255)),
                ("namespace", models.CharField(blank=True, max_length=255)),
                ("status", models.CharField(blank=True, max_length=100)),
                ("error_type", models.CharField(blank=True, max_length=255)),
                ("root_cause", models.TextField(blank=True)),
                ("explanation", models.TextField(blank=True)),
                ("solution", models.TextField(blank=True)),
                ("confidence", models.CharField(blank=True, choices=[("high", "High"), ("medium", "Medium"), ("low", "Low")], max_length=20)),
                ("risk_level", models.CharField(blank=True, choices=[("safe", "Safe"), ("warning", "Warning"), ("block", "Block")], max_length=20)),
                ("is_recurring", models.BooleanField(default=False)),
                ("recurrence_count", models.IntegerField(default=0)),
                ("correlated_service", models.CharField(blank=True, max_length=255)),
                ("correlation_type", models.CharField(blank=True, max_length=50)),
                ("risks", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "analyses"},
        ),
        migrations.CreateModel(
            name="IncidentPattern",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("pod_name", models.CharField(max_length=255)),
                ("namespace", models.CharField(max_length=255)),
                ("error_type", models.CharField(max_length=255)),
                ("occurrence_count", models.IntegerField(default=1)),
                ("first_seen", models.DateTimeField(auto_now_add=True)),
                ("last_seen", models.DateTimeField(auto_now=True)),
                ("last_solution", models.TextField(blank=True)),
            ],
            options={"db_table": "incident_patterns"},
        ),
        migrations.AlterUniqueTogether(
            name="incidentpattern",
            unique_together={("pod_name", "namespace", "error_type")},
        ),
        migrations.AddIndex(
            model_name="analysis",
            index=models.Index(fields=["pod_name", "namespace"], name="analyses_pod_ns_idx"),
        ),
        migrations.AddIndex(
            model_name="analysis",
            index=models.Index(fields=["created_at"], name="analyses_created_idx"),
        ),
        migrations.AddIndex(
            model_name="analysis",
            index=models.Index(fields=["user_id"], name="analyses_user_idx"),
        ),
        migrations.AddIndex(
            model_name="incidentpattern",
            index=models.Index(fields=["pod_name", "namespace"], name="patterns_pod_ns_idx"),
        ),
    ]
