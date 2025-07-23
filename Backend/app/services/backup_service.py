# In file: Backend/app/services/backup_service.py

import asyncio
import httpx
import uuid
import traceback

from app.core.config import settings
from app.db.mongodb import db
from app.models.file import BackupStatus, StorageLocation
from app.services import google_drive_service

# The new "pre-buffering" consumer.
async def prebuffering_consumer(queue: asyncio.Queue, first_chunk: bytes):
    yield first_chunk
    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        yield chunk
        queue.task_done()

# The producer remains the same.
async def producer(queue: asyncio.Queue, gdrive_id: str, account):
    try:
        async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account=account):
            await queue.put(chunk)
        await queue.put(None)
    except Exception as e:
        print(f"!!! [PRODUCER] Error during download: {e}")
        await queue.put(None)
        raise

async def transfer_gdrive_to_hetzner(file_id: str):
    if not all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
        db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.FAILED}}); return

    print(f"[BACKUP_SERVICE] Starting backup task for file_id: {file_id}")
    
    try:
        file_doc = db.files.find_one({"_id": file_id})
        if not file_doc: return

        db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.IN_PROGRESS}})

        file_size = file_doc.get("size_bytes", 0)
        auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
        remote_path = f"{file_id}/{file_doc.get('filename')}"

        directory_url = f"{settings.HETZNER_WEBDAV_URL}/{file_id}"
        async with httpx.AsyncClient(auth=auth) as client:
            mkcol_response = await client.request("MKCOL", directory_url)
            if mkcol_response.status_code not in [201, 405]: mkcol_response.raise_for_status()

        if file_size == 0:
            print(f"[BACKUP_SERVICE] File {file_id} is 0 bytes. Backup complete.")
        else:
            gdrive_id = file_doc.get("gdrive_id")
            gdrive_account_id = file_doc.get("gdrive_account_id")
            source_gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)

            queue = asyncio.Queue(maxsize=5)
            producer_task = asyncio.create_task(producer(queue, gdrive_id, source_gdrive_account))
            
            print("[BACKUP_SERVICE] Waiting for the first chunk from producer...")
            first_chunk = await queue.get()
            
            if first_chunk is None:
                await producer_task
            else:
                print("[BACKUP_SERVICE] First chunk received. Starting Hetzner upload.")
                headers = {'Content-Length': str(file_size)}
                
                # --- FINAL FIX: UNLIMITED WRITE TIMEOUT ---
                # This tells the client: "Wait as long as necessary for the network
                # to be ready to accept more data. Never give up on writing."
                timeout_config = httpx.Timeout(30.0, read=1800.0, write=None)
                # --- END OF FINAL FIX ---
                
                file_upload_url = f"{settings.HETZNER_WEBDAV_URL}/{remote_path}"
                async with httpx.AsyncClient(auth=auth, timeout=timeout_config) as client:
                    response = await client.put(
                        file_upload_url, 
                        content=prebuffering_consumer(queue, first_chunk), 
                        headers=headers
                    )
                    response.raise_for_status()
                
                await producer_task

        print(f"[BACKUP_SERVICE] Successfully transferred file {file_id} to Hetzner.")
        db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.COMPLETED, "backup_location": StorageLocation.HETZNER, "hetzner_remote_path": remote_path}})

    except Exception as e:
        print(f"!!! [BACKUP_SERVICE] An exception occurred for file_id {file_id}."); traceback.print_exc()
        db.files.update_one({"_id": file_id}, {"$set": {"backup_status": BackupStatus.FAILED}})