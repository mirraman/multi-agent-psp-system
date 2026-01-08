import os
from celery import Celery


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


REDIS_URL = _env("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "psp",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)

celery_app.conf.update(
    imports=("app.tasks",),
)

try:
    celery_app.autodiscover_tasks(["app"])
except Exception:
    pass


