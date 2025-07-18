# # # from fastapi import APIRouter, Depends, HTTPException
# # # from fastapi.responses import StreamingResponse
# # # from app.db.mongodb import db
# # # from app.models.file import FileMetadataInDB
# # # from app.services import google_drive_service
# # # from app.services import telegram_service


# # # router = APIRouter()

# # # @router.get("/files/{file_id}/meta", response_model=FileMetadataInDB)
# # # async def get_file_metadata(file_id: str):
# # #     """
# # #     Endpoint to fetch just the metadata for a file.
# # #     The download page will call this to display the file name and size.
# # #     """
# # #     file_doc = db.files.find_one({"_id": file_id})
# # #     if not file_doc:
# # #         raise HTTPException(status_code=404, detail="File not found")
    
# # #     return file_doc

# # # @router.get("/download/stream/{file_id}")
# # # async def stream_download(file_id: str):
# # #     """
# # #     This is the main download endpoint. It intelligently streams the file 
# # #     from its current location (Google Drive or Telegram).
# # #     """
# # #     file_doc = db.files.find_one({"_id": file_id})
# # #     if not file_doc:
# # #         raise HTTPException(status_code=404, detail="File not found")

# # #     filename = file_doc['filename']
# # #     headers = {'Content-Disposition': f'attachment; filename="{filename}"'}

# # #     # --- THE NEW INTELLIGENT LOGIC ---
# # #     storage_location = file_doc.get("storage_location")

# # #     if storage_location == "gdrive":
# # #         print(f"Streaming {file_id} from Google Drive...")
# # #         gdrive_id = file_doc.get("gdrive_id")
# # #         if not gdrive_id:
# # #             raise HTTPException(status_code=404, detail="File is in GDrive but ID is missing.")
# # #         return StreamingResponse(google_drive_service.stream_gdrive_file(gdrive_id), headers=headers)

# # #     elif storage_location == "telegram":
# # #         print(f"Streaming {file_id} from Telegram...")
# # #         file_ids = file_doc.get("telegram_file_ids")
# # #         if not file_ids:
# # #              raise HTTPException(status_code=404, detail="File is in Telegram but IDs are missing.")
# # #         return StreamingResponse(telegram_service.stream_file_from_telegram(file_ids), headers=headers)
        
# # #     else:
# # #         # Handle cases where the file is still uploading or has failed
# # #         raise HTTPException(status_code=404, detail="File is not yet available for download. Please try again later.")



# # ###############################################################################
# # # In file: Backend/app/api/v1/routes_download.py

# # from fastapi import APIRouter, HTTPException, Request
# # from fastapi.responses import StreamingResponse
# # from urllib.parse import quote

# # # --- CHANGE 1: Import the global 'db' object directly ---
# # from app.db.mongodb import db
# # from app.services import google_drive_service, telegram_service
# # from app.models.file import FileMetadataInDB

# # router = APIRouter()

# # @router.get(
# #     "/files/{file_id}/meta",
# #     response_model=FileMetadataInDB,
# #     summary="Get File Metadata",
# #     tags=["Download"]
# # )
# # # --- CHANGE 2: Remove the Depends() since we import 'db' directly ---
# # async def get_file_metadata(file_id: str):
# #     """
# #     Retrieves the metadata for a specific file, such as its name and size.
# #     """
# #     file_doc = await db.files.find_one({"_id": file_id})
# #     if not file_doc:
# #         raise HTTPException(status_code=404, detail="File not found")
# #     return file_doc

# # @router.get(
# #     "/download/stream/{file_id}",
# #     summary="Stream File for Download",
# #     tags=["Download"]
# # )
# # # --- CHANGE 2: Remove the Depends() since we import 'db' directly ---
# # async def stream_download(file_id: str, request: Request):
# #     """
# #     Provides a direct download link for a file.

# #     This endpoint intelligently streams the file from its current storage
# #     location (Google Drive or Telegram) without loading the entire file into
# #     server memory. It responds immediately with headers to prevent timeouts.
# #     """
# #     # 1. Instantly find the file's metadata using the imported 'db' object.
# #     file_doc = await db.files.find_one({"_id": file_id})
# #     if not file_doc:
# #         raise HTTPException(status_code=404, detail="File not found")

# #     filename = file_doc.get("filename", "download")
# #     filesize = file_doc.get("size_bytes", 0)
# #     storage_location = file_doc.get("storage_location")
# #     gdrive_id = file_doc.get("gdrive_id")
# #     telegram_ids = file_doc.get("telegram_file_ids")

# #     # 2. Define the content generator.
# #     async def content_streamer():
# #         print(f"[STREAMER] Starting stream for '{filename}' from {storage_location}.")
# #         try:
# #             if storage_location == "gdrive":
# #                 if not gdrive_id:
# #                     raise ValueError("File is in GDrive but gdrive_id is missing.")
# #                 async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id):
# #                     yield chunk
# #             elif storage_location == "telegram":
# #                 if not telegram_ids:
# #                     raise ValueError("File is in Telegram but telegram_file_ids are missing.")
# #                 async for chunk in telegram_service.stream_file_from_telegram(telegram_ids):
# #                     yield chunk
# #             else:
# #                 print(f"!!! [STREAMER] ERROR: Unknown or missing storage location for file {file_id}")
# #                 raise ValueError("File storage location is unknown or not supported.")
# #             print(f"[STREAMER] Finished streaming '{filename}' successfully.")
# #         except Exception as e:
# #             print(f"!!! [STREAMER] An error occurred during file stream for {file_id}: {e}")

# #     # 3. Construct the headers.
# #     headers = {
# #         "Content-Length": str(filesize),
# #         "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
# #     }

# #     # 4. Return the StreamingResponse.
# #     return StreamingResponse(
# #         content=content_streamer(),
# #         media_type="application/octet-stream",
# #         headers=headers
# #     )



# #####################################################################################################
# #####################################################################################################


# # In file: Backend/app/api/v1/routes_download.py

# from fastapi import APIRouter, HTTPException, Request
# from fastapi.responses import StreamingResponse
# from urllib.parse import quote

# from app.db.mongodb import db
# from app.services import google_drive_service, telegram_service
# from app.models.file import FileMetadataInDB

# router = APIRouter()

# @router.get(
#     "/files/{file_id}/meta",
#     response_model=FileMetadataInDB,
#     summary="Get File Metadata",
#     tags=["Download"]
# )
# # --- CHANGE 1: This function no longer needs to be async. ---
# def get_file_metadata(file_id: str):
#     """
#     Retrieves the metadata for a specific file, such as its name and size.
#     """
#     # --- CHANGE 2: Removed 'await'. db.files.find_one is a synchronous call. ---
#     file_doc = db.files.find_one({"_id": file_id})
#     if not file_doc:
#         raise HTTPException(status_code=404, detail="File not found")
#     return file_doc

# @router.get(
#     "/download/stream/{file_id}",
#     summary="Stream File for Download",
#     tags=["Download"]
# )
# # This function MUST remain async because it uses an async generator.
# async def stream_download(file_id: str, request: Request):
#     """
#     Provides a direct download link for a file.
#     This endpoint intelligently streams the file from its storage location.
#     """
#     # --- CHANGE 3: Removed 'await'. This is also a synchronous call. ---
#     file_doc = db.files.find_one({"_id": file_id})
#     if not file_doc:
#         raise HTTPException(status_code=404, detail="File not found")

#     filename = file_doc.get("filename", "download")
#     filesize = file_doc.get("size_bytes", 0)
#     storage_location = file_doc.get("storage_location")
#     gdrive_id = file_doc.get("gdrive_id")
#     telegram_ids = file_doc.get("telegram_file_ids")

#     # The content_streamer generator is async, so the parent must be too.
#     async def content_streamer():
#         print(f"[STREAMER] Starting stream for '{filename}' from {storage_location}.")
#         try:
#             if storage_location == "gdrive":
#                 if not gdrive_id:
#                     raise ValueError("File is in GDrive but gdrive_id is missing.")
#                 async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id):
#                     yield chunk
#             elif storage_location == "telegram":
#                 if not telegram_ids:
#                     raise ValueError("File is in Telegram but telegram_file_ids are missing.")
#                 async for chunk in telegram_service.stream_file_from_telegram(telegram_ids):
#                     yield chunk
#             else:
#                 print(f"!!! [STREAMER] ERROR: Unknown or missing storage location for file {file_id}")
#                 raise ValueError("File storage location is unknown or not supported.")
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




#########################################################################################################
#########################################################################################################
#########################################################################################################


# In file: Backend/app/api/v1/routes_download.py

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from urllib.parse import quote

from app.db.mongodb import db
# --- MODIFIED: Removed telegram_service import ---
from app.services import google_drive_service
from app.models.file import FileMetadataInDB, StorageLocation

router = APIRouter()

@router.get(
    "/files/{file_id}/meta",
    response_model=FileMetadataInDB,
    summary="Get File Metadata",
    tags=["Download"]
)
def get_file_metadata(file_id: str):
    """
    Retrieves the metadata for a specific file, such as its name and size.
    """
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")
    return file_doc

@router.get(
    "/download/stream/{file_id}",
    summary="Stream File for Download",
    tags=["Download"]
)
async def stream_download(file_id: str, request: Request):
    """
    Provides a direct download link for a file by streaming it from Google Drive.
    """
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")

    filename = file_doc.get("filename", "download")
    filesize = file_doc.get("size_bytes", 0)
    storage_location = file_doc.get("storage_location")
    gdrive_id = file_doc.get("gdrive_id")

    # The content_streamer generator is async, so the parent must be too.
    async def content_streamer():
        print(f"[STREAMER] Starting stream for '{filename}' from {storage_location}.")
        try:
            # --- MODIFIED: Simplified to only handle GDrive ---
            if storage_location == StorageLocation.GDRIVE:
                if not gdrive_id:
                    raise ValueError("File is in GDrive but gdrive_id is missing.")
                async for chunk in google_drive_service.async_stream_gdrive_file(gdrive_id):
                    yield chunk
            else:
                # This case should ideally not be hit with the new logic, but is good for safety.
                print(f"!!! [STREAMER] ERROR: File {file_id} has an invalid or unsupported storage location: {storage_location}")
                raise ValueError("File storage location is unknown or not supported.")
            print(f"[STREAMER] Finished streaming '{filename}' successfully.")
        except Exception as e:
            print(f"!!! [STREAMER] An error occurred during file stream for {file_id}: {e}")

    headers = {
        "Content-Length": str(filesize),
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
    }

    return StreamingResponse(
        content=content_streamer(),
        media_type="application/octet-stream",
        headers=headers
    )