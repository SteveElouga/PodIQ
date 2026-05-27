"""Add workspace_id to Analysis and IncidentPattern for tenant isolation.

- Analysis.workspace_id (nullable UUID, indexed) — scopes analyses per workspace.
- IncidentPattern.workspace_id (nullable UUID, indexed) — scopes patterns per
  workspace; unique_together updated from (pod_name, namespace, error_type) to
  (workspace_id, pod_name, namespace, error_type).

Existing rows (pre-migration) receive workspace_id=NULL, which is treated as
"global/legacy" data. New analyses always carry a workspace_id provided by the
gateway via gRPC, ensuring full tenant isolation going forward.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        # ── Analysis ────────────────────────────────────────────────────────────
        migrations.AddField(
            model_name="analysis",
            name="workspace_id",
            field=models.UUIDField(null=True, blank=True),
        ),
        migrations.AddIndex(
            model_name="analysis",
            index=models.Index(fields=["workspace_id"], name="analyses_workspace_idx"),
        ),
        # ── IncidentPattern ─────────────────────────────────────────────────────
        migrations.AddField(
            model_name="incidentpattern",
            name="workspace_id",
            field=models.UUIDField(null=True, blank=True),
        ),
        # Remove the old global unique constraint before adding the scoped one.
        migrations.AlterUniqueTogether(
            name="incidentpattern",
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name="incidentpattern",
            unique_together={("workspace_id", "pod_name", "namespace", "error_type")},
        ),
        migrations.AddIndex(
            model_name="incidentpattern",
            index=models.Index(fields=["workspace_id"], name="patterns_workspace_idx"),
        ),
    ]
