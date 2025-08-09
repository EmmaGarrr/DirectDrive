# In file: Backend/app/tasks/telegram_uploader_task.py

import io
import time
from app.celery_worker import celery_app
from app.services import google_drive_service, telegram_service
from app.db.mongodb import db
from app.models.file import UploadStatus, StorageLocation
from app.progress_manager import ProgressManager

@celery_app.task(name="tasks.transfer_to_telegram", queue="archive_queue")
def transfer_to_telegram(gdrive_id: str, file_id: str) -> list[str]:
    """
    NEW FLOW: Streams a file from GDrive in chunks and uploads each chunk
    to Telegram, without holding the whole file in RAM.
    """
    print(f"[TELEGRAM_TASK] Starting STREAMING transfer for GDrive file: {gdrive_id}")
    progress = ProgressManager(file_id)
    try:
        file_doc = db.files.find_one({"_id": file_id})
        if not file_doc:
            raise Exception(f"Could not find file metadata for internal id {file_id}")
        original_filename = file_doc.get("filename", "untitled.dat")

        telegram_file_ids = []
        chunk_num = 1
        
        # --- THIS IS THE CORE CHANGE ---
        # We loop through the generator, getting one chunk at a time from GDrive.
        # RAM usage stays low and constant.
        for chunk_data in google_drive_service.stream_gdrive_chunks(
            gdrive_id=gdrive_id,
            chunk_size=telegram_service.TELEGRAM_CHUNK_SIZE_BYTES
        ):
            if not chunk_data:
                continue

            chunk_filename = f"{original_filename}.part_{chunk_num}"
            
            # Upload the chunk we just received to Telegram.
            new_file_id = telegram_service.upload_chunk_and_get_file_id(chunk_data, chunk_filename)
            telegram_file_ids.append(new_file_id)
            
            print(f"[TELEGRAM_TASK] Uploaded chunk {chunk_num} to Telegram.")
            chunk_num += 1
            
            # A short delay to avoid hitting Telegram's rate limits.
            print("[TELEGRAM_TASK] Waiting for 3 seconds to avoid rate limit...")
            time.sleep(3) 
            
        print(f"[TELEGRAM_TASK] All chunks streamed and transferred. File IDs: {telegram_file_ids}")
        return telegram_file_ids

    except Exception as e:
        print(f"!!! [TELEGRAM_TASK] Failed to transfer {gdrive_id} to Telegram: {e}")
        progress.publish_error(f"Failed during Telegram archival: {e}")
        raise

@celery_app.task(name="tasks.finalize_and_delete", queue="archive_queue")
def finalize_and_delete(telegram_file_ids: list[str], file_id: str, gdrive_id: str):
    """
    This final task remains the same. It updates the DB and cleans up the GDrive file.
    """
    try:
        print(f"[FINALIZER_TASK] Starting silent finalization for file_id: {file_id}")
        db.files.update_one(
            {"_id": file_id},
            {
                "$set": {
                    "storage_location": StorageLocation.TELEGRAM,
                    "telegram_file_ids": telegram_file_ids
                },
                "$unset": {"gdrive_id": ""}
            }
        )
        print(f"[FINALIZER_TASK] Database updated for {file_id}. New location: Telegram.")
        google_drive_service.delete_file_with_refresh_token(gdrive_id)
    except Exception as e:
        print(f"!!! [FINALIZER_TASK] Silent finalization FAILED for {file_id}: {e}")