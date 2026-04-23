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
    "app.tasks.worker_tasks.generate_proactive_digest": {"queue": "memory"},
    "app.tasks.worker_tasks.generate_daily_digests": {"queue": "memory"},
    "app.tasks.worker_tasks.generate_weekly_reflections": {"queue": "memory"},
    "app.tasks.worker_tasks.generate_deviation_reminders": {"queue": "memory"},
    "app.tasks.worker_tasks.generate_relationship_reminders": {"queue": "memory"},
    "app.tasks.worker_tasks.backfill_notebook_page_embeddings": {"queue": "memory"},
    "app.tasks.worker_tasks.regenerate_notebook_page_embedding": {"queue": "memory"},
    "app.tasks.worker_tasks.expire_one_time_subscriptions": {"queue": "memory"},
    # Wave 2 A8 — spec §14 alignment
    "app.tasks.worker_tasks.notebook_page_plaintext_task": {"queue": "memory"},
    "app.tasks.worker_tasks.notebook_page_summary_task": {"queue": "inference"},
    "app.tasks.worker_tasks.unified_memory_extract_task": {"queue": "inference"},
    "app.tasks.worker_tasks.notebook_page_memory_link_task": {"queue": "memory"},
    "app.tasks.worker_tasks.notebook_page_relevance_refresh_task": {"queue": "memory"},
    "app.tasks.worker_tasks.whiteboard_memory_extract_task": {"queue": "inference"},
    "app.tasks.worker_tasks.document_memory_extract_task": {"queue": "inference"},
    "app.tasks.worker_tasks.study_asset_chunk_task": {"queue": "data"},
    "app.tasks.worker_tasks.study_asset_auto_pages_task": {"queue": "data"},
    "app.tasks.worker_tasks.study_asset_deck_generate_task": {"queue": "inference"},
    "app.tasks.worker_tasks.study_asset_memory_extract_task": {"queue": "inference"},
    "app.tasks.worker_tasks.study_asset_review_recommendation_task": {"queue": "memory"},
    "app.tasks.worker_tasks.usage_rollup_task": {"queue": "memory"},
    "app.tasks.worker_tasks.subscription_sync_repair_task": {"queue": "memory"},
    # Homepage persona/digest upgrade (spec §2.4)
    "app.tasks.worker_tasks.daily_digest_generate_task": {"queue": "memory"},
    "app.tasks.worker_tasks.weekly_reflection_generate_task": {"queue": "memory"},
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
    "generate-daily-digests": {
        "task": "app.tasks.worker_tasks.generate_daily_digests",
        "schedule": crontab(hour=7, minute=3),
    },
    "generate-weekly-reflections": {
        "task": "app.tasks.worker_tasks.generate_weekly_reflections",
        "schedule": crontab(hour=8, minute=7, day_of_week=1),
    },
    "generate-deviation-reminders": {
        "task": "app.tasks.worker_tasks.generate_deviation_reminders",
        "schedule": crontab(hour=8, minute=12, day_of_week=1),
    },
    "generate-relationship-reminders": {
        "task": "app.tasks.worker_tasks.generate_relationship_reminders",
        "schedule": crontab(hour=8, minute=17, day_of_week=1),
    },
    "backfill-notebook-page-embeddings-nightly": {
        "task": "app.tasks.worker_tasks.backfill_notebook_page_embeddings",
        "schedule": crontab(hour=4, minute=0),
    },
    "expire-one-time-subscriptions-daily": {
        "task": "app.tasks.worker_tasks.expire_one_time_subscriptions",
        "schedule": crontab(hour=2, minute=15),
    },
    # Wave 2 A8 — spec §14 scheduled tasks
    "usage-rollup-daily": {
        "task": "app.tasks.worker_tasks.usage_rollup_task",
        "schedule": crontab(hour=0, minute=0),
    },
    "subscription-sync-repair-6h": {
        "task": "app.tasks.worker_tasks.subscription_sync_repair_task",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    # Homepage daily digest — spec §2.4. Runs hourly; the task body
    # checks each user's IANA timezone and only generates for users
    # whose local clock is 08:xx. This is the per-user timezone path.
    "homepage-daily-digest": {
        "task": "app.tasks.worker_tasks.daily_digest_generate_task",
        "schedule": crontab(minute=30),
    },
    # Homepage weekly reflection — runs hourly; task body matches
    # Sunday 20:xx in user's local time.
    "homepage-weekly-reflection": {
        "task": "app.tasks.worker_tasks.weekly_reflection_generate_task",
        "schedule": crontab(minute=0),
    },
}
