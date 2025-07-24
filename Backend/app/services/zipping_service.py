# File: Backend/app/services/zipping_service.py

import asyncio
import io
import zipfile
from typing import AsyncGenerator

from app.db.mongodb import db
from app.services import google_drive_service
# from app.services import telegram_service

# Define a custom exception for clarity
class FileFetchError(Exception):
    pass

async def stream_file_content(file_doc: dict) -> AsyncGenerator[bytes, None]:
    """
    Intelligently fetches and streams content for a single file
    from its storage location (GDrive or Telegram).
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

        # elif storage_location == "telegram":
        #     telegram_file_ids = file_doc.get("telegram_file_ids")
        #     if not telegram_file_ids:
        #         raise FileFetchError(f"File {file_id} is in Telegram but IDs are missing.")

        #     async for chunk in telegram_service.stream_file_from_telegram(telegram_file_ids):
        #         yield chunk
        else:
            raise FileFetchError(f"File {file_id} has an unknown or unavailable storage location.")
    
    except Exception as e:
        # Re-raise any exception with more context
        print(f"!!! Failed to fetch file {file_id} from {storage_location}: {e}")
        raise FileFetchError(f"Could not retrieve file: {file_doc.get('filename')}") from e


async def stream_zip_archive(batch_id: str) -> AsyncGenerator[bytes, None]:
    """
    Creates a ZIP archive in-memory and streams it chunk by chunk.
    """
    batch_doc = db.batches.find_one({"_id": batch_id})
    if not batch_doc:
        return

    file_ids = batch_doc.get("file_ids", [])
    if not file_ids:
        return

    # Use an in-memory buffer to build the ZIP file
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_id in file_ids:
            file_doc = db.files.find_one({"_id": file_id})
            if not file_doc:
                continue
            
            filename_in_zip = file_doc.get("filename", file_id)
            
            try:
                # Create a writer for the file within the zip archive
                with zf.open(filename_in_zip, 'w') as file_in_zip:
                    async for chunk in stream_file_content(file_doc):
                        file_in_zip.write(chunk)
            except FileFetchError as e:
                # If a single file fails, we can write an error file into the zip
                # to notify the user, and then continue with the next files.
                # IMPORTANT: We do this AFTER the file handle is closed (outside the 'with' block)
                error_filename = f"ERROR_loading_{filename_in_zip}.txt"
                zf.writestr(error_filename, str(e))

    # Once the zip file is fully constructed in the buffer, seek to the start
    zip_buffer.seek(0)
    
    # Yield the zip file in chunks to stream it to the client
    while chunk := zip_buffer.read(65536): # Read in 64KB chunks
        yield chunk