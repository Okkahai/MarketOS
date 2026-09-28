from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "marketos", broker=settings.redis_url, backend=settings.redis_url, include=["app.jobs.tasks"]
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    enable_utc=True,
    # Intervals come from settings; later phases add market, news, AI and evaluation jobs here.
    beat_schedule={
        "heartbeat": {
            "task": "marketos.heartbeat",
            "schedule": float(settings.schedule_heartbeat_seconds),
        },
    },
)
