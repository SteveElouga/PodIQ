import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import dramatiq  # noqa: E402
from dramatiq import Middleware  # noqa: E402


class JobFailureMiddleware(Middleware):
    """Mark the AnalysisJob as FAILED when all Dramatiq retries are exhausted."""

    def after_process_message(self, broker, message, *, result=None, exception=None):
        if exception is None:
            return
        retries = message.options.get("retries", 0)
        max_retries = message.actor_options.get("max_retries", 0)
        if retries < max_retries:
            return  # still has retries left

        job_id = message.args[0] if message.args else message.kwargs.get("job_id")
        if not job_id:
            return
        try:
            from core.models import AnalysisJob

            AnalysisJob.objects.filter(
                id=job_id, status__in=["pending", "running"]
            ).update(
                status=AnalysisJob.Status.FAILED,
                error=f"Task failed after all retries: {exception}",
            )
        except Exception:
            pass


dramatiq.get_broker().add_middleware(JobFailureMiddleware())

from app import tasks  # noqa: F401, E402 — register Dramatiq actors after setup
