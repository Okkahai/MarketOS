from app.db.session import get_session_factory
from app.jobs.celery_app import celery_app
from app.jobs.runner import run_job


@celery_app.task(name="marketos.heartbeat")
def heartbeat() -> str:
    """Proves the worker, beat, broker and database are wired together."""
    with run_job(get_session_factory(), "heartbeat") as ctx:
        ctx.items_written = 0
        return str(ctx.run_id)
