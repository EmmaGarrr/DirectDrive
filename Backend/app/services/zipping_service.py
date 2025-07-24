# File: Backend/app/services/zipping_service.py

import asyncio
import tempfile
import os
from typing import AsyncGenerator, Dict, Any
from zipstream import ZipStream
import aiofiles

from app.db.mongodb import db
from app.services import google_drive_service
# from app.services import telegram_service

# Define a custom exception for clarity
class FileFetchError(Exception):
    pass

class MemoryEfficientZipStreamer:
    """
    Memory-efficient ZIP streaming using temporary files and chunked processing.
    Designed to handle large batches with minimal RAM usage.
    """
    
    def __init__(self, max_memory_usage: int = 50 * 1024 * 1024):  # 50MB max
        self.max_memory_usage = max_memory_usage
        self.temp_dir = tempfile.mkdtemp(prefix="directdrive_zip_")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Clean up temporary directory
        try:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception as e:
            print(f"Warning: Failed to clean up temp directory {self.temp_dir}: {e}")

async def stream_file_content_to_temp(file_doc: dict, temp_path: str) -> tuple[bool, str]:
    """
    Streams file content directly to a temporary file.
    Returns (success, error_message)
    """
    storage_location = file_doc.get("storage_location")
    file_id = file_doc.get("_id")
    
    try:
        if storage_location == "gdrive":
            gdrive_id = file_doc.get("gdrive_id")
            gdrive_account_id = file_doc.get("gdrive_account_id")
            if not gdrive_id:
                return False, f"File {file_id} is in GDrive but ID is missing."
            
            # Get the account configuration for this file
            account = None
            if gdrive_account_id:
                account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)
            
            # Fall back to active account if specific account not found
            if not account:
                account = await google_drive_service.gdrive_pool_manager.get_active_account()
                if not account:
                    return False, f"No Google Drive account available for file {file_id}"
            
            # Stream directly to temporary file
            async with aiofiles.open(temp_path, 'wb') as temp_file:
                async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account):
                    await temp_file.write(chunk)
            
            return True, ""
            
        # elif storage_location == "telegram":
        #     telegram_file_ids = file_doc.get("telegram_file_ids")
        #     if not telegram_file_ids:
        #         return False, f"File {file_id} is in Telegram but IDs are missing."
        #     
        #     async with aiofiles.open(temp_path, 'wb') as temp_file:
        #         async for chunk in telegram_service.stream_file_from_telegram(telegram_file_ids):
        #             await temp_file.write(chunk)
        #     
        #     return True, ""
        else:
            return False, f"File {file_id} has an unknown or unavailable storage location."
    
    except Exception as e:
        print(f"!!! Failed to fetch file {file_id} from {storage_location}: {e}")
        return False, f"Could not retrieve file: {file_doc.get('filename')} - {str(e)}"

async def stream_zip_archive(batch_id: str) -> AsyncGenerator[bytes, None]:
    """
    Memory-efficient ZIP streaming that processes files one at a time
    without loading the entire archive into memory.
    """
    batch_doc = db.batches.find_one({"_id": batch_id})
    if not batch_doc:
        error_msg = f"Batch {batch_id} not found"
        yield error_msg.encode('utf-8')
        return

    file_ids = batch_doc.get("file_ids", [])
    if not file_ids:
        error_msg = f"No files found in batch {batch_id}"
        yield error_msg.encode('utf-8')
        return

    print(f"[ZIP_STREAM] Starting memory-efficient ZIP creation for batch {batch_id} with {len(file_ids)} files")
    
    async with MemoryEfficientZipStreamer() as streamer:
        # Create ZipStream instance for true streaming
        zip_stream = ZipStream(compress_level=6)
        
        # Process files one by one
        for i, file_id in enumerate(file_ids):
            file_doc = db.files.find_one({"_id": file_id})
            if not file_doc:
                print(f"[ZIP_STREAM] Skipping missing file {file_id}")
                continue
            
            filename_in_zip = file_doc.get("filename", file_id)
            temp_file_path = os.path.join(streamer.temp_dir, f"temp_{i}_{file_id}")
            
            print(f"[ZIP_STREAM] Processing file {i+1}/{len(file_ids)}: {filename_in_zip}")
            
            # Stream file to temporary location
            success, error_msg = await stream_file_content_to_temp(file_doc, temp_file_path)
            
            if success and os.path.exists(temp_file_path):
                # Add the temporary file to the ZIP stream
                try:
                    zip_stream.add_path(temp_file_path, arcname=filename_in_zip)
                except Exception as e:
                    print(f"[ZIP_STREAM] Failed to add {filename_in_zip} to ZIP: {e}")
                    # Add error file instead
                    error_content = f"Failed to add file to ZIP: {str(e)}"
                    zip_stream.add_data(f"ERROR_adding_{filename_in_zip}.txt", error_content.encode('utf-8'))
            else:
                # Add error file for failed downloads
                print(f"[ZIP_STREAM] Failed to download {filename_in_zip}: {error_msg}")
                error_content = f"Failed to download file: {error_msg}"
                zip_stream.add_data(f"ERROR_downloading_{filename_in_zip}.txt", error_content.encode('utf-8'))
            
            # Clean up temp file immediately to save disk space
            try:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
            except Exception as e:
                print(f"[ZIP_STREAM] Warning: Failed to clean up temp file {temp_file_path}: {e}")
        
        print(f"[ZIP_STREAM] Starting ZIP stream output for batch {batch_id}")
        
        # Stream the ZIP data in chunks
        try:
            for chunk in zip_stream:
                if chunk:  # Only yield non-empty chunks
                    yield chunk
            
            print(f"[ZIP_STREAM] Successfully completed ZIP stream for batch {batch_id}")
        
        except Exception as e:
            print(f"[ZIP_STREAM] Error during ZIP streaming: {e}")
            error_msg = f"Error during ZIP creation: {str(e)}"
            yield error_msg.encode('utf-8')

# Legacy function kept for backward compatibility (but now uses new implementation)
async def stream_file_content(file_doc: dict) -> AsyncGenerator[bytes, None]:
    """
    Legacy function - streams file content directly (kept for compatibility).
    For ZIP creation, use the new memory-efficient approach above.
    """
    storage_location = file_doc.get("storage_location")
    file_id = file_doc.get("_id")
    
    try:
        if storage_location == "gdrive":
            gdrive_id = file_doc.get("gdrive_id")
            gdrive_account_id = file_doc.get("gdrive_account_id")
            if not gdrive_id:
                raise FileFetchError(f"File {file_id} is in GDrive but ID is missing.")
            
            # Get the account configuration for this file
            account = None
            if gdrive_account_id:
                account = google_drive_service.gdrive_pool_manager.get_account_by_id(gdrive_account_id)
            
            # Fall back to active account if specific account not found
            if not account:
                account = await google_drive_service.gdrive_pool_manager.get_active_account()
                if not account:
                    raise FileFetchError(f"No Google Drive account available for file {file_id}")
            
            async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id, account):
                yield chunk

        else:
            raise FileFetchError(f"File {file_id} has an unknown or unavailable storage location.")
    
    except Exception as e:
        print(f"!!! Failed to fetch file {file_id} from {storage_location}: {e}")
        raise FileFetchError(f"Could not retrieve file: {file_doc.get('filename')}") from e