# # In file: Backend/app/celery_worker.py

# from celery import Celery
# from app.core.config import settings
# from kombu import Queue

# celery_app = Celery(
#     "tasks",
#     broker=settings.CELERY_BROKER_URL,
#     backend=settings.CELERY_BROKER_URL
# )

# # --- MODIFIED: Simplified Queue Configuration ---
# # We now only need the single queue for background archival tasks.
# celery_app.conf.task_queues = (
#     Queue('archive_queue', routing_key='task.archive'),
# )

# # --- MODIFIED: Simplified Routing Rules ---
# # The rule for the obsolete 'upload_to_drive' task has been removed.
# celery_app.conf.task_routes = {
#     'tasks.transfer_to_telegram': {'queue': 'archive_queue', 'routing_key': 'task.archive'},
#     'tasks.finalize_and_delete': {'queue': 'archive_queue', 'routing_key': 'task.archive'},
# }

# # --- MODIFIED: Simplified Imports ---
# # The import for the deleted 'drive_uploader_task' module has been removed.
# celery_app.conf.update(
#     imports=(
#         'app.tasks.telegram_uploader_task',
#     ),
#     task_track_started=True
# )