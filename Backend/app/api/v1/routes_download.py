# # # # # from fastapi import APIRouter, Depends, HTTPException
# # # # # from fastapi.responses import StreamingResponse
# # # # # from app.db.mongodb import db
# # # # # from app.models.file import FileMetadataInDB
# # # # # from app.services import google_drive_service
# # # # # from app.services import telegram_service


# # # # # router = APIRouter()

# # # # # @router.get("/files/{file_id}/meta", response_model=FileMetadataInDB)
# # # # # async def get_file_metadata(file_id: str):
# # # # #     """
# # # # #     Endpoint to fetch just the metadata for a file.
# # # # #     The download page will call this to display the file name and size.
# # # # #     """
# # # # #     file_doc = db.files.find_one({"_id": file_id})
# # # # #     if not file_doc:
# # # # #         raise HTTPException(status_code=404, detail="File not found")
    
# # # # #     return file_doc

# # # # # @router.get("/download/stream/{file_id}")
# # # # # async def stream_download(file_id: str):
# # # # #     """
# # # # #     This is the main download endpoint. It intelligently streams the file 
# # # # #     from its current location (Google Drive or Telegram).
# # # # #     """
# # # # #     file_doc = db.files.find_one({"_id": file_id})
# # # # #     if not file_doc:
# # # # #         raise HTTPException(status_code=404, detail="File not found")

# # # # #     filename = file_doc['filename']
# # # # #     headers = {'Content-Disposition': f'attachment; filename="{filename}"'}

# # # # #     # --- THE NEW INTELLIGENT LOGIC ---
# # # # #     storage_location = file_doc.get("storage_location")

# # # # #     if storage_location == "gdrive":
# # # # #         print(f"Streaming {file_id} from Google Drive...")
# # # # #         gdrive_id = file_doc.get("gdrive_id")
# # # # #         if not gdrive_id:
# # # # #             raise HTTPException(status_code=404, detail="File is in GDrive but ID is missing.")
# # # # #         return StreamingResponse(google_drive_service.stream_gdrive_file(gdrive_id), headers=headers)

# # # # #     elif storage_location == "telegram":
# # # # #         print(f"Streaming {file_id} from Telegram...")
# # # # #         file_ids = file_doc.get("telegram_file_ids")
# # # # #         if not file_ids:
# # # # #              raise HTTPException(status_code=404, detail="File is in Telegram but IDs are missing.")
# # # # #         return StreamingResponse(telegram_service.stream_file_from_telegram(file_ids), headers=headers)
        
# # # # #     else:
# # # # #         # Handle cases where the file is still uploading or has failed
# # # # #         raise HTTPException(status_code=404, detail="File is not yet available for download. Please try again later.")



# # # # ###############################################################################
# # # # # In file: Backend/app/api/v1/routes_download.py

# # # # from fastapi import APIRouter, HTTPException, Request
# # # # from fastapi.responses import StreamingResponse
# # # # from urllib.parse import quote

# # # # # --- CHANGE 1: Import the global 'db' object directly ---
# # # # from app.db.mongodb import db
# # # # from app.services import google_drive_service, telegram_service
# # # # from app.models.file import FileMetadataInDB

# # # # router = APIRouter()

# # # # @router.get(
# # # #     "/files/{file_id}/meta",
# # # #     response_model=FileMetadataInDB,
# # # #     summary="Get File Metadata",
# # # #     tags=["Download"]
# # # # )
# # # # # --- CHANGE 2: Remove the Depends() since we import 'db' directly ---
# # # # async def get_file_metadata(file_id: str):
# # # #     """
# # # #     Retrieves the metadata for a specific file, such as its name and size.
# # # #     """
# # # #     file_doc = await db.files.find_one({"_id": file_id})
# # # #     if not file_doc:
# # # #         raise HTTPException(status_code=404, detail="File not found")
# # # #     return file_doc

# # # # @router.get(
# # # #     "/download/stream/{file_id}",
# # # #     summary="Stream File for Download",
# # # #     tags=["Download"]
# # # # )
# # # # # --- CHANGE 2: Remove the Depends() since we import 'db' directly ---
# # # # async def stream_download(file_id: str, request: Request):
# # # #     """
# # # #     Provides a direct download link for a file.

# # # #     This endpoint intelligently streams the file from its current storage
# # # #     location (Google Drive or Telegram) without loading the entire file into
# # # #     server memory. It responds immediately with headers to prevent timeouts.
# # # #     """
# # # #     # 1. Instantly find the file's metadata using the imported 'db' object.
# # # #     file_doc = await db.files.find_one({"_id": file_id})
# # # #     if not file_doc:
# # # #         raise HTTPException(status_code=404, detail="File not found")

# # # #     filename = file_doc.get("filename", "download")
# # # #     filesize = file_doc.get("size_bytes", 0)
# # # #     storage_location = file_doc.get("storage_location")
# # # #     gdrive_id = file_doc.get("gdrive_id")
# # # #     telegram_ids = file_doc.get("telegram_file_ids")

# # # #     # 2. Define the content generator.
# # # #     async def content_streamer():
# # # #         print(f"[STREAMER] Starting stream for '{filename}' from {storage_location}.")
# # # #         try:
# # # #             if storage_location == "gdrive":
# # # #                 if not gdrive_id:
# # # #                     raise ValueError("File is in GDrive but gdrive_id is missing.")
# # # #                 async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id):
# # # #                     yield chunk
# # # #             elif storage_location == "telegram":
# # # #                 if not telegram_ids:
# # # #                     raise ValueError("File is in Telegram but telegram_file_ids are missing.")
# # # #                 async for chunk in telegram_service.stream_file_from_telegram(telegram_ids):
# # # #                     yield chunk
# # # #             else:
# # # #                 print(f"!!! [STREAMER] ERROR: Unknown or missing storage location for file {file_id}")
# # # #                 raise ValueError("File storage location is unknown or not supported.")
# # # #             print(f"[STREAMER] Finished streaming '{filename}' successfully.")
# # # #         except Exception as e:
# # # #             print(f"!!! [STREAMER] An error occurred during file stream for {file_id}: {e}")

# # # #     # 3. Construct the headers.
# # # #     headers = {
# # # #         "Content-Length": str(filesize),
# # # #         "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
# # # #     }

# # # #     # 4. Return the StreamingResponse.
# # # #     return StreamingResponse(
# # # #         content=content_streamer(),
# # # #         media_type="application/octet-stream",
# # # #         headers=headers
# # # #     )



# # # #####################################################################################################
# # # #####################################################################################################


# # # # In file: Backend/app/api/v1/routes_download.py

# # # from fastapi import APIRouter, HTTPException, Request
# # # from fastapi.responses import StreamingResponse
# # # from urllib.parse import quote

# # # from app.db.mongodb import db
# # # from app.services import google_drive_service, telegram_service
# # # from app.models.file import FileMetadataInDB

# # # router = APIRouter()

# # # @router.get(
# # #     "/files/{file_id}/meta",
# # #     response_model=FileMetadataInDB,
# # #     summary="Get File Metadata",
# # #     tags=["Download"]
# # # )
# # # # --- CHANGE 1: This function no longer needs to be async. ---
# # # def get_file_metadata(file_id: str):
# # #     """
# # #     Retrieves the metadata for a specific file, such as its name and size.
# # #     """
# # #     # --- CHANGE 2: Removed 'await'. db.files.find_one is a synchronous call. ---
# # #     file_doc = db.files.find_one({"_id": file_id})
# # #     if not file_doc:
# # #         raise HTTPException(status_code=404, detail="File not found")
# # #     return file_doc

# # # @router.get(
# # #     "/download/stream/{file_id}",
# # #     summary="Stream File for Download",
# # #     tags=["Download"]
# # # )
# # # # This function MUST remain async because it uses an async generator.
# # # async def stream_download(file_id: str, request: Request):
# # #     """
# # #     Provides a direct download link for a file.
# # #     This endpoint intelligently streams the file from its storage location.
# # #     """
# # #     # --- CHANGE 3: Removed 'await'. This is also a synchronous call. ---
# # #     file_doc = db.files.find_one({"_id": file_id})
# # #     if not file_doc:
# # #         raise HTTPException(status_code=404, detail="File not found")

# # #     filename = file_doc.get("filename", "download")
# # #     filesize = file_doc.get("size_bytes", 0)
# # #     storage_location = file_doc.get("storage_location")
# # #     gdrive_id = file_doc.get("gdrive_id")
# # #     telegram_ids = file_doc.get("telegram_file_ids")

# # #     # The content_streamer generator is async, so the parent must be too.
# # #     async def content_streamer():
# # #         print(f"[STREAMER] Starting stream for '{filename}' from {storage_location}.")
# # #         try:
# # #             if storage_location == "gdrive":
# # #                 if not gdrive_id:
# # #                     raise ValueError("File is in GDrive but gdrive_id is missing.")
# # #                 async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id):
# # #                     yield chunk
# # #             elif storage_location == "telegram":
# # #                 if not telegram_ids:
# # #                     raise ValueError("File is in Telegram but telegram_file_ids are missing.")
# # #                 async for chunk in telegram_service.stream_file_from_telegram(telegram_ids):
# # #                     yield chunk
# # #             else:
# # #                 print(f"!!! [STREAMER] ERROR: Unknown or missing storage location for file {file_id}")
# # #                 raise ValueError("File storage location is unknown or not supported.")
# # #             print(f"[STREAMER] Finished streaming '{filename}' successfully.")
# # #         except Exception as e:
# # #             print(f"!!! [STREAMER] An error occurred during file stream for {file_id}: {e}")

# # #     headers = {
# # #         "Content-Length": str(filesize),
# # #         "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
# # #     }

# # #     return StreamingResponse(
# # #         content=content_streamer(),
# # #         media_type="application/octet-stream",
# # #         headers=headers
# # #     )




# # #########################################################################################################
# # #########################################################################################################
# # #########################################################################################################


# # # In file: Backend/app/api/v1/routes_download.py

# # from fastapi import APIRouter, HTTPException, Request
# # from fastapi.responses import StreamingResponse
# # from urllib.parse import quote
# # import datetime
# # from app.ws_manager import manager

# # from app.db.mongodb import db
# # # --- MODIFIED: Removed telegram_service import ---
# # from app.services import google_drive_service
# # from app.models.file import FileMetadataInDB, StorageLocation
# # from datetime import datetime
# # router = APIRouter()

# # @router.get(
# #     "/files/{file_id}/meta",
# #     response_model=FileMetadataInDB,
# #     summary="Get File Metadata",
# #     tags=["Download"]
# # )
# # def get_file_metadata(file_id: str):
# #     """
# #     Retrieves the metadata for a specific file, such as its name and size.
# #     """
# #     file_doc = db.files.find_one({"_id": file_id})
# #     if not file_doc:
# #         raise HTTPException(status_code=404, detail="File not found")
# #     return file_doc

# # @router.get(
# #     "/download/stream/{file_id}",
# #     summary="Stream File for Download",
# #     tags=["Download"]
# # )
# # async def stream_download(file_id: str, request: Request):
# #     """
# #     Provides a direct download link for a file by streaming it from Google Drive.
# #     """
# #     file_doc = db.files.find_one({"_id": file_id})
# #     if not file_doc:
# #         raise HTTPException(status_code=404, detail="File not found")

# #     filename = file_doc.get("filename", "download")
# #     filesize = file_doc.get("size_bytes", 0)
# #     storage_location = file_doc.get("storage_location")
# #     gdrive_id = file_doc.get("gdrive_id")

# #     # The content_streamer generator is async, so the parent must be too.
# #     async def content_streamer():
# #         # ADD THIS BROADCAST
# #         timestamp = datetime.utcnow().isoformat()
# #         await manager.broadcast(f"[{timestamp}] [API_REQUEST] Google Drive: Start File Download for '{filename}' (file_id: {file_id})")

# #         print(f"[STREAMER] Starting stream for '{filename}' from {storage_location}.")
# #         try:
# #             # --- MODIFIED: Simplified to only handle GDrive ---
# #             if storage_location == StorageLocation.GDRIVE:
# #                 if not gdrive_id:
# #                     raise ValueError("File is in GDrive but gdrive_id is missing.")
# #                 async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id):
# #                     yield chunk
# #             else:
# #                 # This case should ideally not be hit with the new logic, but is good for safety.
# #                 print(f"!!! [STREAMER] ERROR: File {file_id} has an invalid or unsupported storage location: {storage_location}")
# #                 raise ValueError("File storage location is unknown or not supported.")
# #             print(f"[STREAMER] Finished streaming '{filename}' successfully.")
# #         except Exception as e:
# #             print(f"!!! [STREAMER] An error occurred during file stream for {file_id}: {e}")

# #     headers = {
# #         "Content-Length": str(filesize),
# #         "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
# #     }

# #     return StreamingResponse(
# #         content=content_streamer(),
# #         media_type="application/octet-stream",
# #         headers=headers
# #     )



# # In file: Backend/app/api/v1/routes_download.py

# from fastapi import APIRouter, HTTPException, Request
# from fastapi.responses import StreamingResponse
# from urllib.parse import quote
# from datetime import datetime

# from app.db.mongodb import db
# # --- MODIFIED: Import the pool manager and helper functions ---
# from app.services.google_drive_service import gdrive_pool_manager, async_stream_gdrive_file
# from app.models.file import FileMetadataInDB, StorageLocation
# # from app.ws_manager import manager

# router = APIRouter()

# @router.get(
#     "/files/{file_id}/meta",
#     response_model=FileMetadataInDB,
#     summary="Get File Metadata"
# )
# def get_file_metadata(file_id: str):
#     file_doc = db.files.find_one({"_id": file_id})
#     if not file_doc:
#         raise HTTPException(status_code=404, detail="File not found")
#     return file_doc

# @router.get(
#     "/download/stream/{file_id}",
#     summary="Stream File for Download"
# )
# async def stream_download(file_id: str, request: Request):
#     file_doc = db.files.find_one({"_id": file_id})
#     if not file_doc:
#         raise HTTPException(status_code=404, detail="File not found")

#     filename = file_doc.get("filename", "download")
#     filesize = file_doc.get("size_bytes", 0)
#     gdrive_id = file_doc.get("gdrive_id")
    
#     # --- NEW: Find out which account the file is stored on ---
#     account_id = file_doc.get("gdrive_account_id")
#     if not account_id:
#         raise HTTPException(status_code=500, detail="File metadata is incomplete: missing account ID.")

#     # --- NEW: Get the specific account credentials from the pool ---
#     storage_account = gdrive_pool_manager.get_account_by_id(account_id)
#     if not storage_account:
#         raise HTTPException(status_code=500, detail=f"Configuration for storage account '{account_id}' not found.")

#     if not gdrive_id:
#         raise HTTPException(status_code=404, detail="File is in GDrive but ID is missing in metadata.")

#     async def content_streamer():
#         # timestamp = datetime.utcnow().isoformat()
#         # await manager.broadcast(f"[{timestamp}] [API_REQUEST] Google Drive: Start File Download for '{filename}'")

#         print(f"[STREAMER] Starting stream for '{filename}' from account {storage_account.id}.")
#         try:
#             # --- MODIFIED: Pass the specific storage_account to the stream function ---
#             async for chunk in async_stream_gdrive_file(gdrive_id, account=storage_account):
#                 yield chunk
#             print(f"[STREAMER] Finished streaming '{filename}' successfully.")
#         except Exception as e:
#             print(f"!!! [STREAMER] An error occurred during file stream for {file_id}: {e}")

#     headers = {
#         "Content-Length": str(filesize),
#         "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
#     }

#     return StreamingResponse(
#         content=content_streamer(),
#         media_type="application/octet-stream",
#         headers=headers
#     )




# In file: Backend/app/api/v1/routes_download.py

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from urllib.parse import quote
import httpx # --- NEW: Import httpx for Hetzner downloads ---

from app.db.mongodb import db
from app.core.config import settings # --- NEW: Import settings for credentials ---
from app.services.google_drive_service import gdrive_pool_manager, async_stream_gdrive_file
from app.models.file import FileMetadataInDB

router = APIRouter()

@router.get(
    "/files/{file_id}/meta",
    response_model=FileMetadataInDB,
    summary="Get File Metadata"
)
def get_file_metadata(file_id: str):
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")
    return file_doc

@router.get(
    "/download/stream/{file_id}",
    summary="Stream File for Download"
)
async def stream_download(file_id: str, request: Request):
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")

    filename = file_doc.get("filename", "download")
    filesize = file_doc.get("size_bytes", 0)

    # This async generator now contains the smart fallback logic
    async def content_streamer():
        # --- PRIMARY ATTEMPT: GOOGLE DRIVE ---
        try:
            print(f"[STREAMER] Attempting primary download from Google Drive for '{filename}'...")
            gdrive_id = file_doc.get("gdrive_id")
            account_id = file_doc.get("gdrive_account_id")

            if not gdrive_id or not account_id:
                raise ValueError("Primary storage info (GDrive) is missing from metadata.")
            
            storage_account = gdrive_pool_manager.get_account_by_id(account_id)
            if not storage_account:
                raise ValueError(f"Configuration for GDrive account '{account_id}' not found.")

            # If successful, this loop will run and stream the file
            async for chunk in async_stream_gdrive_file(gdrive_id, account=storage_account):
                yield chunk
            
            print(f"[STREAMER] Successfully streamed '{filename}' from Google Drive.")
            return # IMPORTANT: Exit the generator after a successful primary download

        except Exception as e:
            print(f"!!! [STREAMER] Primary download from Google Drive failed: {e}. Attempting backup from Hetzner...")

        # --- FALLBACK ATTEMPT: HETZNER ---
        try:
            print(f"[STREAMER] Attempting fallback download from Hetzner for '{filename}'...")
            hetzner_path = file_doc.get("hetzner_remote_path")
            if not hetzner_path:
                raise ValueError("Backup storage info (Hetzner) is missing from metadata.")
            
            hetzner_url = f"{settings.HETZNER_WEBDAV_URL}/{hetzner_path}"
            auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
            timeout = httpx.Timeout(10.0, read=3600.0)

            async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
                async with client.stream("GET", hetzner_url) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
            
            print(f"[STREAMER] Successfully streamed '{filename}' from Hetzner backup.")

        except Exception as e:
            print(f"!!! [STREAMER] Fallback download from Hetzner also failed for '{filename}': {e}")
            # If both attempts fail, the generator will simply stop, and the user
            # will receive an empty/failed download, which is the correct behavior.
    
    headers = {
        "Content-Length": str(filesize),
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
    }

    return StreamingResponse(
        content=content_streamer(),
        media_type="application/octet-stream",
        headers=headers
    )