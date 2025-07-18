# # # In file: Backend/app/tasks/telegram_uploader_task.py

# # import io
# # import time
# # from app.celery_worker import celery_app
# # from app.services import google_drive_service, telegram_service
# # from app.db.mongodb import db
# # from app.models.file import UploadStatus, StorageLocation
# # from app.progress_manager import ProgressManager

# # # --- REWRITTEN FOR LOW MEMORY USAGE ---
# # @celery_app.task(name="tasks.transfer_to_telegram", queue="archive_queue", bind=True)
# # def transfer_to_telegram(self, gdrive_id: str, file_id: str) -> list[str]:
# #     """
# #     Streams a file from GDrive chunk-by-chunk and uploads each chunk directly
# #     to Telegram, ensuring minimal memory usage.
# #     """
# #     print(f"[TELEGRAM_TASK] Starting STREAMING transfer for GDrive file: {gdrive_id}")
# #     progress = ProgressManager(file_id)
# #     try:
# #         file_doc = db.files.find_one({"_id": file_id})
# #         if not file_doc:
# #             raise Exception(f"Could not find file metadata for internal id {file_id}")
# #         original_filename = file_doc.get("filename", "untitled.dat")

# #         telegram_file_ids = []
# #         chunk_num = 1
        
# #         # This is the core of the new logic. We loop through the generator.
# #         # Each 'chunk_data' is only ~18MB, keeping RAM usage low.
# #         for chunk_data in google_drive_service.stream_gdrive_chunks(
# #             gdrive_id=gdrive_id, 
# #             chunk_size=telegram_service.TELEGRAM_CHUNK_SIZE_BYTES
# #         ):
# #             if not chunk_data:
# #                 continue

# #             chunk_filename = f"{original_filename}.part_{chunk_num}"
# #             print(f"[TELEGRAM_TASK] Uploading chunk {chunk_num} to Telegram...")

# #             new_file_id = telegram_service.upload_chunk_and_get_file_id(chunk_data, chunk_filename)
# #             telegram_file_ids.append(new_file_id)
# #             chunk_num += 1
            
# #             # A short delay to avoid hitting Telegram's rate limits
# #             print("[TELEGRAM_TASK] Waiting for 3 seconds to avoid rate limit...")
# #             time.sleep(3)
            
# #         print(f"[TELEGRAM_TASK] All chunks transferred via streaming. File IDs: {telegram_file_ids}")
# #         return telegram_file_ids

# #     except Exception as e:
# #         print(f"!!! [TELEGRAM_TASK] Streaming transfer failed for {gdrive_id}: {e}")
# #         progress.publish_error(f"Failed during archival: {e}")
# #         # Retry the task after a delay if it fails.
# #         raise self.retry(exc=e, countdown=60)


# # # The finalize_and_delete task remains the same, as it's already correct.
# # @celery_app.task(name="tasks.finalize_and_delete", queue="archive_queue")
# # def finalize_and_delete(telegram_file_ids: list[str], file_id: str, gdrive_id: str):
# #     """
# #     This is the final, silent task. It updates the DB to point to Telegram
# #     as the new storage location and cleans up the temporary file from GDrive.
# #     """
# #     try:
# #         print(f"[FINALIZER_TASK] Starting silent finalization for file_id: {file_id}")
# #         db.files.update_one(
# #             {"_id": file_id},
# #             {
# #                 "$set": {
# #                     "storage_location": StorageLocation.TELEGRAM,
# #                     "telegram_file_ids": telegram_file_ids
# #                 },
# #                 "$unset": {"gdrive_id": ""}
# #             }
# #         )
# #         print(f"[FINALIZER_TASK] Database updated for {file_id}. New location: Telegram.")
# #         google_drive_service.delete_file_with_refresh_token(gdrive_id)
# #     except Exception as e:
# #         print(f"!!! [FINALIZER_TASK] Silent finalization FAILED for {file_id}: {e}")

# #telegram_uploader_task.py:

# import io
# import time
# from app.celery_worker import celery_app
# from app.services import google_drive_service, telegram_service
# from app.db.mongodb import db
# from app.models.file import UploadStatus, StorageLocation
# from app.progress_manager import ProgressManager

# @celery_app.task(name="tasks.transfer_to_telegram", queue="archive_queue")
# def transfer_to_telegram(gdrive_id: str, file_id: str) -> list[str]:
#     """
#     Downloads from GDrive, uploads to Telegram, and returns a list of Telegram file_ids.
#     """
#     print(f"[TELEGRAM_TASK] Starting transfer for GDrive file: {gdrive_id}")
#     progress = ProgressManager(file_id)
#     try:
#         file_doc = db.files.find_one({"_id": file_id})
#         if not file_doc:
#             raise Exception(f"Could not find file metadata for internal id {file_id}")
#         original_filename = file_doc.get("filename", "untitled.dat")

#         file_bytes_io = google_drive_service.download_file_from_gdrive(gdrive_id)
        
#         # This will hold the string-based file_ids
#         telegram_file_ids = []
#         chunk_num = 1
        
#         while True:
#             chunk_data = file_bytes_io.read(telegram_service.TELEGRAM_CHUNK_SIZE_BYTES)
#             if not chunk_data:
#                 break
            
#             chunk_filename = f"{original_filename}.part_{chunk_num}"
            
#             # --- FIX: Call the correct function that now exists ---
#             new_file_id = telegram_service.upload_chunk_and_get_file_id(chunk_data, chunk_filename)
#             telegram_file_ids.append(new_file_id)
#             chunk_num += 1
            
#             # A short delay to avoid hitting Telegram's rate limits
#             print("[TELEGRAM_TASK] Waiting for 3 seconds to avoid rate limit...")
#             time.sleep(3) 
            
#         print(f"[TELEGRAM_TASK] All chunks transferred. File IDs: {telegram_file_ids}")
#         return telegram_file_ids

#     except Exception as e:
#         print(f"!!! [TELEGRAM_TASK] Failed to transfer {gdrive_id} to Telegram: {e}")
#         # If this background task fails, we notify the user via the progress socket.
#         progress.publish_error(f"Failed during Telegram archival: {e}")
#         raise

# @celery_app.task(name="tasks.finalize_and_delete", queue="archive_queue")
# def finalize_and_delete(telegram_file_ids: list[str], file_id: str, gdrive_id: str):
#     """
#     This is the final, silent task. It updates the DB to point to Telegram
#     as the new storage location and cleans up the temporary file from GDrive.
#     It does NOT notify the user, as they already received a success message.
#     """
#     try:
#         print(f"[FINALIZER_TASK] Starting silent finalization for file_id: {file_id}")
#         db.files.update_one(
#             {"_id": file_id},
#             {
#                 "$set": {
#                     # This is the crucial update. The file is now officially in Telegram.
#                     "storage_location": StorageLocation.TELEGRAM,
#                     "telegram_file_ids": telegram_file_ids
#                 },
#                 # Remove the temporary GDrive ID
#                 "$unset": {"gdrive_id": ""}
#             }
#         )
#         print(f"[FINALIZER_TASK] Database updated for {file_id}. New location: Telegram.")

#         # Clean up the file from Google Drive
#         google_drive_service.delete_file_with_refresh_token(gdrive_id)

#     except Exception as e:
#         # If this silent task fails, we just log it. The user already has a working
#         # download link to the GDrive file, so we don't send another notification.
#         print(f"!!! [FINALIZER_TASK] Silent finalization FAILED for {file_id}: {e}")


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