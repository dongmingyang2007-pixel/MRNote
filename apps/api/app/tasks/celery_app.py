from celery import Celery
from celery.schedules import crontab

from app.core.config import settings


celery_app = Celery("qihang", broker=settings.redis_url, include=["app.tasks.worker_tasks"])
celery_app.conf.task_routes = {
    "app.tasks.worker_tasks.process_data_item": {"queue": "data"},
    "app.tasks.worker_tasks.cleanup_deleted_dataset": {"queue": "cleanup"},
    "app.tasks.worker_tasks.cleanup_deleted_project": {"queue": "cleanup"},
    "app.tasks.worker_tasks.cleanup_pending_upload_session": {"queue": "cleanup"},
    "app.tasks.worker_tasks.cleanup_pending_model_artifact_upload": {"queue": "cleanup"},
    "app.tasks.worker_tasks.purge_stale_records": {"queue": "cleanup"},
    "app.tasks.worker_tasks.index_data_item": {"queue": "data"},
    "app.tasks.worker_tasks.extract_memories": {"queue": "inference"},
    "app.tasks.worker_tasks.compact_project_memories": {"queue": "memory"},
    "app.tasks.worker_tasks.repair_project_memory_graph": {"queue": "memory"},
    "app.tasks.worker_tasks.backfill_project_memory_v2": {"queue": "memory"},
    "app.tasks.worker_tasks.run_project_memory_sleep_cycle": {"queue": "memory"},
    "app.tasks.worker_tasks.run_nightly_memory_sleep_cycle": {"queue": "memory"},
}
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    event_serializer="json",
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    task_send_sent_event=False,
    worker_send_task_events=False,
)
celery_app.conf.beat_schedule = {
    "purge-stale-records-daily": {
        "task": "app.tasks.worker_tasks.purge_stale_records",
        "schedule": crontab(hour=3, minute=0),
    },
    "memory-sleep-cycle-nightly": {
        "task": "app.tasks.worker_tasks.run_nightly_memory_sleep_cycle",
        "schedule": crontab(hour=2, minute=30),
    },
}
