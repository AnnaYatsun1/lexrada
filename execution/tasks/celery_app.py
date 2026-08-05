"""Конфигурация Celery."""
import os
from celery import Celery

celery = Celery(
    "lexradar",
    broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
    include=["execution.tasks.analyze"],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,  # Postgres = source of truth
    task_track_started=True,
    task_time_limit=300,
)
# celery.autodiscover_tasks(["execution.tasks"])