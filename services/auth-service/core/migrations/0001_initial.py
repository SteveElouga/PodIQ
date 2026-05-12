import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies: list = []

    operations = [
        migrations.CreateModel(
            name="User",
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
                ("email", models.EmailField(max_length=255, unique=True)),
                ("password_hash", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "users"},
        ),
        migrations.CreateModel(
            name="ApiKey",
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
                ("key_hash", models.CharField(max_length=255)),
                ("name", models.CharField(blank=True, max_length=100)),
                ("last_used", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "api_keys"},
        ),
        migrations.AddIndex(
            model_name="apikey",
            index=models.Index(fields=["user_id"], name="apikey_user_idx"),
        ),
        migrations.AddIndex(
            model_name="apikey",
            index=models.Index(fields=["key_hash"], name="apikey_hash_idx"),
        ),
    ]
