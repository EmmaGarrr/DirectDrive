# # # # # # # # # In file: Backend/app/services/hetzner_service.py

# # # # # # # # import asyncio
# # # # # # # # import httpx
# # # # # # # # import uuid

# # # # # # # # from app.core.config import settings
# # # # # # # # from app.db.mongodb import db
# # # # # # # # from app.models.file import BackupStatus, StorageLocation
# # # # # # # # from app.services import google_drive_service

# # # # # # # # async def transfer_gdrive_to_hetzner(file_id: str):
# # # # # # # #     """
# # # # # # # #     This is the background task function. It performs a stream-to-stream
# # # # # # # #     transfer from Google Drive to Hetzner Storage Box.
# # # # # # # #     """
# # # # # # # #     print(f"[HETZNER_BACKUP] Starting backup task for file_id: {file_id}")
    
# # # # # # # #     try:
# # # # # # # #         # Step 1: Find the file metadata and mark backup as in-progress
# # # # # # # #         file_doc = db.files.find_one({"_id": file_id})
# # # # # # # #         if not file_doc:
# # # # # # # #             print(f"!!! [HETZNER_BACKUP] File {file_id} not found in DB. Aborting.")
# # # # # # # #             return

# # # # # # # #         db.files.update_one(
# # # # # # # #             {"_id": file_id},
# # # # # # # #             {"$set": {"backup_status": BackupStatus.IN_PROGRESS}}
# # # # # # # #         )

# # # # # # # #         # Step 2: Get the specific Google Drive account the file was uploaded to
# # # # # # # #         gdrive_id = file_doc.get("gdrive_id")
# # # # # # # #         gdrive_account_id = file_doc.get("gdrive_account_id")

# # # # # # # #         if not gdrive_id or not gdrive_account_id:
# # # # # # # #             raise ValueError("Missing gdrive_id or gdrive_account_id in file metadata.")
            
# # # # # # # #         source_gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)
# # # # # # # #         if not source_gdrive_account:
# # # # # # # #             raise ValueError(f"Could not find configuration for Google account: {gdrive_account_id}")

# # # # # # # #         # Step 3: Prepare the Hetzner destination URL and authentication
# # # # # # # #         # We will store files in a directory structure based on the original file_id
# # # # # # # #         # to ensure uniqueness and organization.
# # # # # # # #         remote_path = f"{file_id}/{file_doc.get('filename')}"
# # # # # # # #         hetzner_url = f"{settings.HETZNER_WEBDAV_URL}/{remote_path}"
# # # # # # # #         auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)

# # # # # # # #         # The data for the PUT request will be our async generator
# # # # # # # #         async def stream_generator():
# # # # # # # #             print(f"[HETZNER_BACKUP] Starting GDrive stream for {gdrive_id}")
# # # # # # # #             async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account=source_gdrive_account):
# # # # # # # #                 yield chunk
# # # # # # # #             print(f"[HETZNER_BACKUP] Finished GDrive stream for {gdrive_id}")

# # # # # # # #         # Step 4: Perform the stream-to-stream transfer
# # # # # # # #         # We use a long timeout to accommodate large file transfers.
# # # # # # # #         timeout = httpx.Timeout(10.0, read=3600.0) # 1 hour read timeout
# # # # # # # #         async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
# # # # # # # #             print(f"[HETZNER_BACKUP] Streaming to Hetzner URL: {hetzner_url}")
# # # # # # # #             response = await client.put(hetzner_url, content=stream_generator())
# # # # # # # #             response.raise_for_status() # Will raise an error for non-2xx responses

# # # # # # # #         print(f"[HETZNER_BACKUP] Successfully transferred file {file_id} to Hetzner.")

# # # # # # # #         # Step 5: Update the database with the successful backup information
# # # # # # # #         db.files.update_one(
# # # # # # # #             {"_id": file_id},
# # # # # # # #             {"$set": {
# # # # # # # #                 "backup_status": BackupStatus.COMPLETED,
# # # # # # # #                 "backup_location": StorageLocation.HETZNER,
# # # # # # # #                 "hetzner_remote_path": remote_path
# # # # # # # #             }}
# # # # # # # #         )

# # # # # # # #     except Exception as e:
# # # # # # # #         print(f"!!! [HETZNER_BACKUP] FAILED for file_id {file_id}. Reason: {e}")
# # # # # # # #         # Mark the backup as failed in the database
# # # # # # # #         db.files.update_one(
# # # # # # # #             {"_id": file_id},
# # # # # # # #             {"$set": {"backup_status": BackupStatus.FAILED}}
# # # # # # # #         )




# # # # # # # # In file: Backend/app/services/hetzner_service.py

# # # # # # # import asyncio
# # # # # # # import httpx
# # # # # # # import uuid

# # # # # # # from app.core.config import settings
# # # # # # # from app.db.mongodb import db
# # # # # # # from app.models.file import BackupStatus, StorageLocation
# # # # # # # from app.services import google_drive_service

# # # # # # # async def transfer_gdrive_to_hetzner(file_id: str):
# # # # # # #     """
# # # # # # #     This is the background task function. It performs a stream-to-stream
# # # # # # #     transfer from Google Drive to Hetzner Storage Box.
# # # # # # #     """
# # # # # # #     print(f"[HETZNER_BACKUP] Starting backup task for file_id: {file_id}")
    
# # # # # # #     try:
# # # # # # #         # Step 1: Find the file metadata and mark backup as in-progress
# # # # # # #         file_doc = db.files.find_one({"_id": file_id})
# # # # # # #         if not file_doc:
# # # # # # #             print(f"!!! [HETZNER_BACKUP] File {file_id} not found in DB. Aborting.")
# # # # # # #             return

# # # # # # #         db.files.update_one(
# # # # # # #             {"_id": file_id},
# # # # # # #             {"$set": {"backup_status": BackupStatus.IN_PROGRESS}}
# # # # # # #         )

# # # # # # #         # Step 2: Get the specific Google Drive account the file was uploaded to
# # # # # # #         gdrive_id = file_doc.get("gdrive_id")
# # # # # # #         gdrive_account_id = file_doc.get("gdrive_account_id")

# # # # # # #         if not gdrive_id or not gdrive_account_id:
# # # # # # #             raise ValueError("Missing gdrive_id or gdrive_account_id in file metadata.")
            
# # # # # # #         source_gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)
# # # # # # #         if not source_gdrive_account:
# # # # # # #             raise ValueError(f"Could not find configuration for Google account: {gdrive_account_id}")

# # # # # # #         # Step 3: Prepare the Hetzner destination URL and authentication
# # # # # # #         remote_path = f"{file_id}/{file_doc.get('filename')}"
# # # # # # #         hetzner_url = f"{settings.HETZNER_WEBDAV_URL}/{remote_path}"
# # # # # # #         auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)

# # # # # # #         # This generator now has the final safety net.
# # # # # # #         async def stream_generator():
# # # # # # #             print(f"[HETZNER_BACKUP] Starting GDrive stream for {gdrive_id}")
# # # # # # #             async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account=source_gdrive_account):
# # # # # # #                 # --- THIS IS THE FINAL FIX ---
# # # # # # #                 # Only yield the chunk if it is not None and not empty.
# # # # # # #                 # This makes the uploader immune to any bad data from the source stream.
# # # # # # #                 if chunk:
# # # # # # #                     yield chunk
# # # # # # #                 # --- END OF FINAL FIX ---
# # # # # # #             print(f"[HETZNER_BACKUP] Finished GDrive stream for {gdrive_id}")

# # # # # # #         # Step 4: Perform the stream-to-stream transfer
# # # # # # #         timeout = httpx.Timeout(10.0, read=3600.0)
# # # # # # #         async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
# # # # # # #             print(f"[HETZNER_BACKUP] Streaming to Hetzner URL: {hetzner_url}")
# # # # # # #             response = await client.put(hetzner_url, content=stream_generator())
# # # # # # #             response.raise_for_status()

# # # # # # #         print(f"[HETZNER_BACKUP] Successfully transferred file {file_id} to Hetzner.")

# # # # # # #         # Step 5: Update the database with the successful backup information
# # # # # # #         db.files.update_one(
# # # # # # #             {"_id": file_id},
# # # # # # #             {"$set": {
# # # # # # #                 "backup_status": BackupStatus.COMPLETED,
# # # # # # #                 "backup_location": StorageLocation.HETZNER,
# # # # # # #                 "hetzner_remote_path": remote_path
# # # # # # #             }}
# # # # # # #         )

# # # # # # #     except Exception as e:
# # # # # # #         print(f"!!! [HETZNER_BACKUP] FAILED for file_id {file_id}. Reason: {e}")
# # # # # # #         db.files.update_one(
# # # # # # #             {"_id": file_id},
# # # # # # #             {"$set": {"backup_status": BackupStatus.FAILED}}
# # # # # # #         )





# # # # # # # In file: Backend/app/services/hetzner_service.py

# # # # # # import asyncio
# # # # # # import httpx
# # # # # # import uuid
# # # # # # import traceback # --- NEW: Import the traceback module for detailed error logging ---

# # # # # # from app.core.config import settings
# # # # # # from app.db.mongodb import db
# # # # # # from app.models.file import BackupStatus, StorageLocation
# # # # # # from app.services import google_drive_service

# # # # # # async def transfer_gdrive_to_hetzner(file_id: str):
# # # # # #     """
# # # # # #     This is the background task function with enhanced diagnostic logging.
# # # # # #     """
# # # # # #     print(f"[HETZNER_BACKUP] Starting backup task for file_id: {file_id}")
    
# # # # # #     try:
# # # # # #         file_doc = db.files.find_one({"_id": file_id})
# # # # # #         if not file_doc:
# # # # # #             print(f"!!! [HETZNER_BACKUP] File {file_id} not found in DB. Aborting.")
# # # # # #             return

# # # # # #         db.files.update_one(
# # # # # #             {"_id": file_id},
# # # # # #             {"$set": {"backup_status": BackupStatus.IN_PROGRESS}}
# # # # # #         )

# # # # # #         gdrive_id = file_doc.get("gdrive_id")
# # # # # #         gdrive_account_id = file_doc.get("gdrive_account_id")

# # # # # #         if not gdrive_id or not gdrive_account_id:
# # # # # #             raise ValueError("Missing gdrive_id or gdrive_account_id in file metadata.")
            
# # # # # #         source_gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)
# # # # # #         if not source_gdrive_account:
# # # # # #             raise ValueError(f"Could not find configuration for Google account: {gdrive_account_id}")

# # # # # #         remote_path = f"{file_id}/{file_doc.get('filename')}"
# # # # # #         hetzner_url = f"{settings.HETZNER_WEBDAV_URL}/{remote_path}"
# # # # # #         auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)

# # # # # #         async def stream_generator():
# # # # # #             print(f"[HETZNER_DEBUG] Starting GDrive stream for {gdrive_id}")
# # # # # #             # We will now inspect every single chunk that comes from the Google Drive service.
# # # # # #             async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account=source_gdrive_account):
# # # # # #                 # --- NEW: DETAILED LOGGING ---
# # # # # #                 # This log will tell us the exact type and size of each chunk.
# # # # # #                 chunk_type = type(chunk)
# # # # # #                 chunk_len = len(chunk) if chunk is not None else "N/A"
# # # # # #                 print(f"[HETZNER_DEBUG] Received chunk from GDrive. Type: {chunk_type}, Length: {chunk_len}")
# # # # # #                 # --- END OF NEW LOGGING ---
                
# # # # # #                 # The safety check remains.
# # # # # #                 if chunk:
# # # # # #                     yield chunk
# # # # # #             print(f"[HETZNER_DEBUG] Finished GDrive stream for {gdrive_id}")

# # # # # #         timeout = httpx.Timeout(10.0, read=3600.0)
# # # # # #         async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
# # # # # #             print(f"[HETZNER_DEBUG] Preparing to stream to Hetzner URL: {hetzner_url}")
# # # # # #             response = await client.put(hetzner_url, content=stream_generator())
# # # # # #             response.raise_for_status()

# # # # # #         print(f"[HETZNER_BACKUP] Successfully transferred file {file_id} to Hetzner.")

# # # # # #         db.files.update_one(
# # # # # #             {"_id": file_id},
# # # # # #             {"$set": {
# # # # # #                 "backup_status": BackupStatus.COMPLETED,
# # # # # #                 "backup_location": StorageLocation.HETZNER,
# # # # # #                 "hetzner_remote_path": remote_path
# # # # # #             }}
# # # # # #         )

# # # # # #     except Exception as e:
# # # # # #         # --- NEW: DETAILED ERROR REPORTING ---
# # # # # #         print(f"!!! [HETZNER_BACKUP] An exception occurred for file_id {file_id}. Reason: {e}")
# # # # # #         print("--- FULL TRACEBACK ---")
# # # # # #         traceback.print_exc() # This prints the full error stack trace.
# # # # # #         print("----------------------")
# # # # # #         # --- END OF NEW REPORTING ---

# # # # # #         db.files.update_one(
# # # # # #             {"_id": file_id},
# # # # # #             {"$set": {"backup_status": BackupStatus.FAILED}}
# # # # # #         )





# # # # # # In file: Backend/app/services/hetzner_service.py

# # # # # import asyncio
# # # # # import httpx
# # # # # import uuid
# # # # # import traceback

# # # # # from app.core.config import settings
# # # # # from app.db.mongodb import db
# # # # # from app.models.file import BackupStatus, StorageLocation
# # # # # from app.services import google_drive_service

# # # # # async def transfer_gdrive_to_hetzner(file_id: str):
# # # # #     """
# # # # #     This is the background task function with a pre-flight check for credentials.
# # # # #     """
# # # # #     # --- NEW: PRE-FLIGHT CHECK FOR CREDENTIALS ---
# # # # #     # This check happens BEFORE anything else.
# # # # #     if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
# # # # #         print("!!! [HETZNER_BACKUP] CRITICAL ERROR: Hetzner credentials are not configured in the .env file.")
# # # # #         print("!!! Please add HETZNER_WEBDAV_URL, HETZNER_USERNAME, and HETZNER_PASSWORD to your .env file.")
# # # # #         db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.FAILED}})
# # # # #         return # Stop the function immediately.
# # # # #     # --- END OF PRE-FLIGHT CHECK ---

# # # # #     print(f"[HETZNER_BACKUP] Starting backup task for file_id: {file_id}")
    
# # # # #     try:
# # # # #         file_doc = db.files.find_one({"_id": file_id})
# # # # #         if not file_doc:
# # # # #             print(f"!!! [HETZNER_BACKUP] File {file_id} not found in DB. Aborting.")
# # # # #             return

# # # # #         db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.IN_PROGRESS}})

# # # # #         gdrive_id = file_doc.get("gdrive_id")
# # # # #         gdrive_account_id = file_doc.get("gdrive_account_id")

# # # # #         if not gdrive_id or not gdrive_account_id:
# # # # #             raise ValueError("Missing gdrive_id or gdrive_account_id in file metadata.")
            
# # # # #         source_gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)
# # # # #         if not source_gdrive_account:
# # # # #             raise ValueError(f"Could not find configuration for Google account: {gdrive_account_id}")

# # # # #         remote_path = f"{file_id}/{file_doc.get('filename')}"
# # # # #         hetzner_url = f"{settings.HETZNER_WEBDAV_URL}/{remote_path}"
# # # # #         auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)

# # # # #         async def stream_generator():
# # # # #             async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account=source_gdrive_account):
# # # # #                 if chunk:
# # # # #                     yield chunk

# # # # #         timeout = httpx.Timeout(10.0, read=3600.0)
# # # # #         async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
# # # # #             response = await client.put(hetzner_url, content=stream_generator())
# # # # #             response.raise_for_status()

# # # # #         print(f"[HETZNER_BACKUP] Successfully transferred file {file_id} to Hetzner.")

# # # # #         db.files.update_one(
# # # # #             {"_id": file_id},
# # # # #             {"$set": {
# # # # #                 "backup_status": BackupStatus.COMPLETED,
# # # # #                 "backup_location": StorageLocation.HETZNER,
# # # # #                 "hetzner_remote_path": remote_path
# # # # #             }}
# # # # #         )

# # # # #     except Exception as e:
# # # # #         print(f"!!! [HETZNER_BACKUP] An exception occurred for file_id {file_id}. Reason: {e}")
# # # # #         traceback.print_exc()
# # # # #         db.files.update_one(
# # # # #             {"_id": file_id},
# # # # #             {"$set": {"backup_status": BackupStatus.FAILED}}
# # # # #         )




# # # # # In file: Backend/app/services/hetzner_service.py

# # # # import asyncio
# # # # import httpx
# # # # import uuid
# # # # import traceback

# # # # from app.core.config import settings
# # # # from app.db.mongodb import db
# # # # from app.models.file import BackupStatus, StorageLocation
# # # # from app.services import google_drive_service

# # # # async def transfer_gdrive_to_hetzner(file_id: str):
# # # #     """
# # # #     This is the final background task function. It creates the parent
# # # #     directory on Hetzner before streaming the file.
# # # #     """
# # # #     if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
# # # #         print("!!! [HETZNER_BACKUP] CRITICAL ERROR: Hetzner credentials are not configured in the .env file.")
# # # #         db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.FAILED}})
# # # #         return

# # # #     print(f"[HETZNER_BACKUP] Starting backup task for file_id: {file_id}")
    
# # # #     try:
# # # #         file_doc = db.files.find_one({"_id": file_id})
# # # #         if not file_doc:
# # # #             print(f"!!! [HETZNER_BACKUP] File {file_id} not found in DB. Aborting.")
# # # #             return

# # # #         db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.IN_PROGRESS}})

# # # #         gdrive_id = file_doc.get("gdrive_id")
# # # #         gdrive_account_id = file_doc.get("gdrive_account_id")

# # # #         if not gdrive_id or not gdrive_account_id:
# # # #             raise ValueError("Missing gdrive_id or gdrive_account_id in file metadata.")
            
# # # #         source_gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)
# # # #         if not source_gdrive_account:
# # # #             raise ValueError(f"Could not find configuration for Google account: {gdrive_account_id}")

# # # #         # Prepare paths and authentication
# # # #         remote_path = f"{file_id}/{file_doc.get('filename')}"
# # # #         auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)

# # # #         # --- NEW: STEP 1 - CREATE THE PARENT DIRECTORY ---
# # # #         # The directory is just the file_id part of the path
# # # #         directory_url = f"{settings.HETZNER_WEBDAV_URL}/{file_id}"
# # # #         print(f"[HETZNER_BACKUP] Attempting to create directory: {directory_url}")
# # # #         async with httpx.AsyncClient(auth=auth) as client:
# # # #             # MKCOL is the WebDAV method to "Make Collection" (a directory)
# # # #             response = await client.request("MKCOL", directory_url)
# # # #             # A 405 "Method Not Allowed" is OK here - it just means the directory already exists.
# # # #             if response.status_code not in [201, 405]:
# # # #                 response.raise_for_status()
# # # #         print(f"[HETZNER_BACKUP] Directory created or already exists.")
# # # #         # --- END OF NEW STEP ---

# # # #         # The generator for streaming data from Google Drive
# # # #         async def stream_generator():
# # # #             async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account=source_gdrive_account):
# # # #                 if chunk:
# # # #                     yield chunk

# # # #         # --- STEP 2 - UPLOAD THE FILE INTO THE DIRECTORY ---
# # # #         file_upload_url = f"{settings.HETZNER_WEBDAV_URL}/{remote_path}"
# # # #         timeout = httpx.Timeout(10.0, read=3600.0)
# # # #         async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
# # # #             print(f"[HETZNER_BACKUP] Streaming file to: {file_upload_url}")
# # # #             response = await client.put(file_upload_url, content=stream_generator())
# # # #             response.raise_for_status()

# # # #         print(f"[HETZNER_BACKUP] Successfully transferred file {file_id} to Hetzner.")

# # # #         # Final DB update
# # # #         db.files.update_one(
# # # #             {"_id": file_id},
# # # #             {"$set": {
# # # #                 "backup_status": BackupStatus.COMPLETED,
# # # #                 "backup_location": StorageLocation.HETZNER,
# # # #                 "hetzner_remote_path": remote_path
# # # #             }}
# # # #         )

# # # #     except Exception as e:
# # # #         print(f"!!! [HETZNER_BACKUP] An exception occurred for file_id {file_id}. Reason: {e}")
# # # #         traceback.print_exc()
# # # #         db.files.update_one(
# # # #             {"_id": file_id},
# # # #             {"$set": {"backup_status": BackupStatus.FAILED}}
# # # #         )





# # # # In file: Backend/app/services/hetzner_service.py

# # # import asyncio
# # # import httpx
# # # import uuid
# # # import traceback

# # # from app.core.config import settings
# # # from app.db.mongodb import db
# # # from app.models.file import BackupStatus, StorageLocation
# # # from app.services import google_drive_service

# # # async def transfer_gdrive_to_hetzner(file_id: str):
# # #     """
# # #     This is the final diagnostic version. It will log the exact response
# # #     from the directory creation attempt.
# # #     """
# # #     if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
# # #         print("!!! [HETZNER_BACKUP] CRITICAL ERROR: Hetzner credentials are not configured in the .env file.")
# # #         db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.FAILED}})
# # #         return

# # #     print(f"[HETZNER_BACKUP] Starting backup task for file_id: {file_id}")
    
# # #     try:
# # #         file_doc = db.files.find_one({"_id": file_id})
# # #         if not file_doc:
# # #             print(f"!!! [HETZNER_BACKUP] File {file_id} not found in DB. Aborting.")
# # #             return

# # #         db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.IN_PROGRESS}})

# # #         gdrive_id = file_doc.get("gdrive_id")
# # #         gdrive_account_id = file_doc.get("gdrive_account_id")

# # #         if not gdrive_id or not gdrive_account_id:
# # #             raise ValueError("Missing gdrive_id or gdrive_account_id in file metadata.")
            
# # #         source_gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)
# # #         if not source_gdrive_account:
# # #             raise ValueError(f"Could not find configuration for Google account: {gdrive_account_id}")

# # #         remote_path = f"{file_id}/{file_doc.get('filename')}"
# # #         auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)

# # #         # Step 1 - Create the parent directory
# # #         directory_url = f"{settings.HETZNER_WEBDAV_URL}/{file_id}"
# # #         async with httpx.AsyncClient(auth=auth) as client:
# # #             response = await client.request("MKCOL", directory_url)
            
# # #             # --- FINAL DIAGNOSTIC LOG ---
# # #             # This will show us exactly how Hetzner responded to the MKCOL command.
# # #             print(f"[HETZNER_DEBUG] MKCOL response for '{directory_url}': STATUS={response.status_code}, TEXT={response.text}")
# # #             # --- END OF DIAGNOSTIC LOG ---

# # #             if response.status_code not in [201, 405]: # 201 = Created, 405 = Already Exists
# # #                 response.raise_for_status()
        
# # #         # The generator for streaming data from Google Drive
# # #         async def stream_generator():
# # #             async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account=source_gdrive_account):
# # #                 if chunk:
# # #                     yield chunk

# # #         # Step 2 - Upload the file into the directory
# # #         file_upload_url = f"{settings.HETZNER_WEBDAV_URL}/{remote_path}"
# # #         timeout = httpx.Timeout(10.0, read=3600.0)
# # #         async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
# # #             response = await client.put(file_upload_url, content=stream_generator())
# # #             response.raise_for_status()

# # #         print(f"[HETZNER_BACKUP] Successfully transferred file {file_id} to Hetzner.")

# # #         # Final DB update
# # #         db.files.update_one(
# # #             {"_id": file_id},
# # #             {"$set": {
# # #                 "backup_status": BackupStatus.COMPLETED,
# # #                 "backup_location": StorageLocation.HETZNER,
# # #                 "hetzner_remote_path": remote_path
# # #             }}
# # #         )

# # #     except Exception as e:
# # #         print(f"!!! [HETZNER_BACKUP] An exception occurred for file_id {file_id}. Reason: {e}")
# # #         traceback.print_exc()
# # #         db.files.update_one(
# # #             {"_id": file_id},
# # #             {"$set": {"backup_status": BackupStatus.FAILED}}
# # #         )





# # # In file: Backend/app/services/hetzner_service.py

# # import asyncio
# # import httpx
# # import uuid
# # import traceback

# # from app.core.config import settings
# # from app.db.mongodb import db
# # from app.models.file import BackupStatus, StorageLocation
# # from app.services import google_drive_service

# # async def transfer_gdrive_to_hetzner(file_id: str):
# #     """
# #     This is the final, production-ready version. It adds a Content-Length
# #     header to the upload request for maximum compatibility.
# #     """
# #     if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
# #         print("!!! [HETZNER_BACKUP] CRITICAL ERROR: Hetzner credentials are not configured in the .env file.")
# #         db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.FAILED}})
# #         return

# #     print(f"[HETZNER_BACKUP] Starting backup task for file_id: {file_id}")
    
# #     try:
# #         file_doc = db.files.find_one({"_id": file_id})
# #         if not file_doc:
# #             print(f"!!! [HETZNER_BACKUP] File {file_id} not found in DB. Aborting.")
# #             return

# #         db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.IN_PROGRESS}})

# #         gdrive_id = file_doc.get("gdrive_id")
# #         gdrive_account_id = file_doc.get("gdrive_account_id")

# #         if not gdrive_id or not gdrive_account_id:
# #             raise ValueError("Missing gdrive_id or gdrive_account_id in file metadata.")
            
# #         source_gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)
# #         if not source_gdrive_account:
# #             raise ValueError(f"Could not find configuration for Google account: {gdrive_account_id}")

# #         remote_path = f"{file_id}/{file_doc.get('filename')}"
# #         auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)

# #         # Step 1 - Create the parent directory
# #         directory_url = f"{settings.HETZNER_WEBDAV_URL}/{file_id}"
# #         async with httpx.AsyncClient(auth=auth) as client:
# #             response = await client.request("MKCOL", directory_url)
# #             if response.status_code not in [201, 405]: # 201=Created, 405=Already Exists
# #                 response.raise_for_status()
        
# #         # The generator for streaming data from Google Drive
# #         async def stream_generator():
# #             async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account=source_gdrive_account):
# #                 if chunk:
# #                     yield chunk

# #         # --- FINAL FIX: ADDING THE CONTENT-LENGTH HEADER ---
# #         # Get the file's exact size from the database.
# #         file_size = file_doc.get("size_bytes", 0)
# #         # Create headers to tell the server the exact size of the content.
# #         headers = {'Content-Length': str(file_size)}
# #         # --- END OF FINAL FIX ---
        
# #         # Step 2 - Upload the file into the directory
# #         file_upload_url = f"{settings.HETZNER_WEBDAV_URL}/{remote_path}"
# #         timeout = httpx.Timeout(10.0, read=3600.0)
# #         async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
# #             print(f"[HETZNER_BACKUP] Streaming file to: {file_upload_url} with Content-Length: {file_size}")
# #             # Pass the new headers along with the request.
# #             response = await client.put(file_upload_url, content=stream_generator(), headers=headers)
# #             response.raise_for_status()

# #         print(f"[HETZNER_BACKUP] Successfully transferred file {file_id} to Hetzner.")

# #         # Final DB update
# #         db.files.update_one(
# #             {"_id": file_id},
# #             {"$set": {
# #                 "backup_status": BackupStatus.COMPLETED,
# #                 "backup_location": StorageLocation.HETZNER,
# #                 "hetzner_remote_path": remote_path
# #             }}
# #         )

# #     except Exception as e:
# #         print(f"!!! [HETZNER_BACKUP] An exception occurred for file_id {file_id}. Reason: {e}")
# #         traceback.print_exc()
# #         db.files.update_one(
# #             {"_id": file_id},
# #             {"$set": {"backup_status": BackupStatus.FAILED}}
# #         )



# # In file: Backend/app/services/hetzner_service.py

# import asyncio
# import httpx
# import uuid
# import traceback

# from app.core.config import settings
# from app.db.mongodb import db
# from app.models.file import BackupStatus, StorageLocation
# from app.services import google_drive_service

# async def transfer_gdrive_to_hetzner(file_id: str):
#     """
#     This is the final, production-ready version with an extended timeout
#     for large file transfers.
#     """
#     if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
#         print("!!! [HETZNER_BACKUP] CRITICAL ERROR: Hetzner credentials are not configured in the .env file.")
#         db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.FAILED}})
#         return

#     print(f"[HETZNER_BACKUP] Starting backup task for file_id: {file_id}")
    
#     try:
#         file_doc = db.files.find_one({"_id": file_id})
#         if not file_doc:
#             print(f"!!! [HETZNER_BACKUP] File {file_id} not found in DB. Aborting.")
#             return

#         db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.IN_PROGRESS}})

#         gdrive_id = file_doc.get("gdrive_id")
#         gdrive_account_id = file_doc.get("gdrive_account_id")

#         if not gdrive_id or not gdrive_account_id:
#             raise ValueError("Missing gdrive_id or gdrive_account_id in file metadata.")
            
#         source_gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)
#         if not source_gdrive_account:
#             raise ValueError(f"Could not find configuration for Google account: {gdrive_account_id}")

#         remote_path = f"{file_id}/{file_doc.get('filename')}"
#         auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)

#         # Step 1 - Create the parent directory
#         directory_url = f"{settings.HETZNER_WEBDAV_URL}/{file_id}"
#         async with httpx.AsyncClient(auth=auth) as client:
#             response = await client.request("MKCOL", directory_url)
#             if response.status_code not in [201, 405]: # 201=Created, 405=Already Exists
#                 response.raise_for_status()
        
#         # The generator for streaming data from Google Drive
#         async def stream_generator():
#             async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account=source_gdrive_account):
#                 if chunk:
#                     yield chunk

#         # Get the file's exact size from the database.
#         file_size = file_doc.get("size_bytes", 0)
#         headers = {'Content-Length': str(file_size)}
        
#         # --- FINAL FIX: A GENEROUS, GLOBAL TIMEOUT ---
#         # Set a 30-minute (1800 seconds) timeout for the entire request.
#         # This gives ample time for large files to be transferred and processed.
#         timeout = 1800.0
#         # --- END OF FINAL FIX ---
        
#         # Step 2 - Upload the file into the directory
#         file_upload_url = f"{settings.HETZNER_WEBDAV_URL}/{remote_path}"
#         async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
#             print(f"[HETZNER_BACKUP] Streaming file to: {file_upload_url} with Content-Length: {file_size}")
#             response = await client.put(file_upload_url, content=stream_generator(), headers=headers)
#             response.raise_for_status()

#         print(f"[HETZNER_BACKUP] Successfully transferred file {file_id} to Hetzner.")

#         # Final DB update
#         db.files.update_one(
#             {"_id": file_id},
#             {"$set": {
#                 "backup_status": BackupStatus.COMPLETED,
#                 "backup_location": StorageLocation.HETZNER,
#                 "hetzner_remote_path": remote_path
#             }}
#         )

#     except Exception as e:
#         print(f"!!! [HETZNER_BACKUP] An exception occurred for file_id {file_id}. Reason: {e}")
#         traceback.print_exc()
#         db.files.update_one(
#             {"_id": file_id},
#             {"$set": {"backup_status": BackupStatus.FAILED}}
#         )



# In file: Backend/app/services/hetzner_service.py

import asyncio
import httpx
import uuid
import traceback

from app.core.config import settings
from app.db.mongodb import db
from app.models.file import BackupStatus, StorageLocation
from app.services import google_drive_service

async def transfer_gdrive_to_hetzner(file_id: str):
    """
    This is the final, production-ready version with an extended timeout
    for large file transfers.
    """
    if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
        print("!!! [HETZNER_BACKUP] CRITICAL ERROR: Hetzner credentials are not configured in the .env file.")
        db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.FAILED}})
        return

    print(f"[HETZNER_BACKUP] Starting backup task for file_id: {file_id}")
    
    try:
        file_doc = db.files.find_one({"_id": file_id})
        if not file_doc:
            print(f"!!! [HETZNER_BACKUP] File {file_id} not found in DB. Aborting.")
            return

        db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.IN_PROGRESS}})

        gdrive_id = file_doc.get("gdrive_id")
        gdrive_account_id = file_doc.get("gdrive_account_id")

        if not gdrive_id or not gdrive_account_id:
            raise ValueError("Missing gdrive_id or gdrive_account_id in file metadata.")
            
        source_gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)
        if not source_gdrive_account:
            raise ValueError(f"Could not find configuration for Google account: {gdrive_account_id}")

        remote_path = f"{file_id}/{file_doc.get('filename')}"
        auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)

        # Step 1 - Create the parent directory
        directory_url = f"{settings.HETZNER_WEBDAV_URL}/{file_id}"
        async with httpx.AsyncClient(auth=auth) as client:
            response = await client.request("MKCOL", directory_url)
            if response.status_code not in [201, 405]: # 201=Created, 405=Already Exists
                response.raise_for_status()
        
        # The generator for streaming data from Google Drive
        async def stream_generator():
            async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account=source_gdrive_account):
                if chunk:
                    yield chunk

        # Get the file's exact size from the database.
        file_size = file_doc.get("size_bytes", 0)
        headers = {'Content-Length': str(file_size)}
        
        # --- FINAL FIX: A GENEROUS, GLOBAL TIMEOUT ---
        # Set a 30-minute (1800 seconds) timeout for the entire request.
        # This gives ample time for large files to be transferred and processed.
        timeout = 1800.0
        # --- END OF FINAL FIX ---
        
        # Step 2 - Upload the file into the directory
        file_upload_url = f"{settings.HETZNER_WEBDAV_URL}/{remote_path}"
        async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
            print(f"[HETZNER_BACKUP] Streaming file to: {file_upload_url} with Content-Length: {file_size}")
            response = await client.put(file_upload_url, content=stream_generator(), headers=headers)
            response.raise_for_status()

        print(f"[HETZNER_BACKUP] Successfully transferred file {file_id} to Hetzner.")

        # Final DB update
        db.files.update_one(
            {"_id": file_id},
            {"$set": {
                "backup_status": BackupStatus.COMPLETED,
                "backup_location": StorageLocation.HETZNER,
                "hetzner_remote_path": remote_path
            }}
        )

    except Exception as e:
        print(f"!!! [HETZNER_BACKUP] An exception occurred for file_id {file_id}. Reason: {e}")
        traceback.print_exc()
        db.files.update_one(
            {"_id": file_id},
            {"$set": {"backup_status": BackupStatus.FAILED}}
        )