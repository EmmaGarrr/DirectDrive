# # # # In file: Backend/app/api/v1/routes_upload.py

# # # import uuid
# # # import json
# # # import httpx
# # # from typing import Optional

# # # from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
# # # from celery import chain

# # # from app.models.file import FileMetadataCreate, FileMetadataInDB, InitiateUploadRequest, UploadStatus, StorageLocation
# # # from app.models.user import UserInDB
# # # from app.db.mongodb import db
# # # from app.services.auth_service import get_current_user_optional, get_current_user
# # # from app.services import google_drive_service
# # # from app.tasks.telegram_uploader_task import transfer_to_telegram, finalize_and_delete

# # # router = APIRouter()
# # # ws_router = APIRouter()

# # # # The UPLOAD_DIR is no longer needed. We are not storing files locally.
# # # # UPLOAD_DIR = Path("temp_uploads")
# # # # UPLOAD_DIR.mkdir(exist_ok=True)

# # # # --- REWRITTEN: The /initiate endpoint ---
# # # @router.post("/upload/initiate", response_model=dict)
# # # async def initiate_upload(
# # #     request: InitiateUploadRequest,
# # #     current_user: Optional[UserInDB] = Depends(get_current_user_optional)
# # # ):
# # #     """
# # #     NEW FLOW - Step 1:
# # #     - Frontend announces its intent to upload.
# # #     - Backend contacts Google Drive to get a resumable upload session URL.
# # #     - Backend creates the DB record and returns the file_id and the GDrive URL.
# # #     """
# # #     file_id = str(uuid.uuid4())
    
# # #     try:
# # #         # Call our new service function to get the unique, one-time upload URL from Google Drive
# # #         gdrive_upload_url = google_drive_service.create_resumable_upload_session(
# # #             filename=request.filename,
# # #             filesize=request.size
# # #         )
# # #     except Exception as e:
# # #         print(f"!!! FAILED to create Google Drive resumable session: {e}")
# # #         raise HTTPException(status_code=503, detail="Cloud storage service is currently unavailable.")

# # #     # Create the initial database record
# # #     file_meta = FileMetadataCreate(
# # #         _id=file_id,
# # #         filename=request.filename,
# # #         size_bytes=request.size,
# # #         content_type=request.content_type,
# # #         owner_id=current_user.id if current_user else None,
# # #         status=UploadStatus.PENDING # Status is pending until the WebSocket connects
# # #     )
# # #     db.files.insert_one(file_meta.model_dump(by_alias=True))
    
# # #     # Return both the internal file_id and the GDrive session URL to the frontend
# # #     return {"file_id": file_id, "gdrive_upload_url": gdrive_upload_url}


# # # # --- COMPLETELY REWRITTEN: The WebSocket handler ---
# # # @ws_router.websocket("/ws/upload/{file_id}/{gdrive_upload_url:path}")
# # # async def websocket_upload_proxy(
# # #     websocket: WebSocket,
# # #     file_id: str,
# # #     gdrive_upload_url: str
# # # ):
# # #     """
# # #     NEW FLOW - Step 2: This endpoint acts as a streaming proxy (a "pipe").
# # #     - It receives chunks from the browser.
# # #     - It immediately forwards them to the Google Drive resumable upload URL.
# # #     - It sends progress back to the browser.
# # #     - It does NOT save the file to the server disk.
# # #     """
# # #     await websocket.accept()
    
# # #     file_doc = db.files.find_one({"_id": file_id})
# # #     if not file_doc:
# # #         await websocket.close(code=1008, reason="File ID not found")
# # #         return

# # #     total_size = file_doc.get("size_bytes", 0)
# # #     bytes_sent = 0

# # #     # Use an async HTTP client to send data to Google
# # #     async with httpx.AsyncClient(timeout=None) as client:
# # #         try:
# # #             db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.UPLOADING_TO_DRIVE}})
            
# # #             while True:
# # #                 message = await websocket.receive()
# # #                 chunk = message.get("bytes")
                
# # #                 if not chunk:
# # #                     # Could be a 'DONE' message or other text, we ignore it and wait for bytes
# # #                     # Or check for a 'DONE' text message to break, but relying on size is more robust
# # #                     if "text" in message and message["text"] == "DONE":
# # #                         break
# # #                     continue
                
# # #                 # Prepare the request for Google Drive
# # #                 start_byte = bytes_sent
# # #                 end_byte = bytes_sent + len(chunk) - 1
                
# # #                 headers = {
# # #                     'Content-Length': str(len(chunk)),
# # #                     'Content-Range': f'bytes {start_byte}-{end_byte}/{total_size}'
# # #                 }
                
# # #                 # Forward the chunk to Google Drive
# # #                 response = await client.put(gdrive_upload_url, content=chunk, headers=headers)
                
# # #                 # Check Google's response for errors
# # #                 if response.status_code not in [200, 201, 308]: # 308 is "Resume Incomplete", which is OK
# # #                     error_detail = f"Google Drive API Error: {response.text}"
# # #                     print(f"!!! [{file_id}] {error_detail}")
# # #                     raise HTTPException(status_code=response.status_code, detail=error_detail)

# # #                 bytes_sent += len(chunk)
# # #                 percentage = int((bytes_sent / total_size) * 100)
# # #                 await websocket.send_json({"type": "progress", "value": percentage})

# # #             # The final response from Google contains the file metadata including its ID
# # #             if response.status_code not in [200, 201]:
# # #                  raise Exception(f"Final Google Drive response was not successful: Status {response.status_code}")
                 
# # #             gdrive_response_data = response.json()
# # #             gdrive_id = gdrive_response_data.get('id')

# # #             if not gdrive_id:
# # #                 raise Exception("Upload to Google Drive succeeded, but no file ID was returned.")

# # #             print(f"[{file_id}] GDrive upload successful. GDrive ID: {gdrive_id}")

# # #             # Update DB with the permanent gdrive_id and mark as completed
# # #             db.files.update_one(
# # #                 {"_id": file_id},
# # #                 {"$set": {
# # #                     "gdrive_id": gdrive_id,
# # #                     "status": UploadStatus.COMPLETED,
# # #                     "storage_location": StorageLocation.GDRIVE 
# # #                 }}
# # #             )

# # #             # Send final success message to the user
# # #             download_path = f"/api/v1/download/stream/{file_id}"
# # #             await websocket.send_json({"type": "success", "value": download_path})
            
# # #             # Kick off the SILENT background archival task using a Celery chain
# # #             print(f"[{file_id}] Dispatching silent Telegram archival task chain.")
# # #             task_chain = chain(
# # #                 transfer_to_telegram.s(gdrive_id=gdrive_id, file_id=file_id),
# # #                 finalize_and_delete.s(file_id=file_id, gdrive_id=gdrive_id)
# # #             )
# # #             task_chain.delay()

# # #         except (WebSocketDisconnect, RuntimeError, httpx.RequestError, HTTPException, Exception) as e:
# # #             print(f"!!! [{file_id}] Upload proxy failed: {e}")
# # #             db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.FAILED}})
# # #             try:
# # #                  await websocket.send_json({"type": "error", "value": "Upload failed. Please try again."})
# # #             except RuntimeError:
# # #                 pass # Websocket already closed, can't send error
# # #         finally:
# # #             if websocket.client_state != "DISCONNECTED":
# # #                 await websocket.close()
# # #             print(f"[{file_id}] WebSocket proxy connection closed for file_id.")


# # # # --- HTTP routes for metadata/history remain the same ---
# # # @router.get("/files/{file_id}", response_model=FileMetadataInDB)
# # # async def get_file_metadata(file_id: str):
# # #     file_doc = db.files.find_one({"_id": file_id})
# # #     if not file_doc:
# # #         raise HTTPException(status_code=404, detail="File not found")
# # #     return FileMetadataInDB(**file_doc)

# # # @router.get("/files/me/history", response_model=list[FileMetadataInDB])
# # # async def get_user_file_history(current_user: UserInDB = Depends(get_current_user)):
# # #     files = db.files.find({"owner_id": current_user.id})
# # #     return [FileMetadataInDB(**f) for f in files]


# # # In file: Backend/app/api/v1/routes_upload.py

# # import uuid
# # import json
# # import httpx
# # from typing import Optional

# # from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
# # from celery import chain

# # from app.models.file import FileMetadataCreate, FileMetadataInDB, InitiateUploadRequest, UploadStatus, StorageLocation
# # from app.models.user import UserInDB
# # from app.db.mongodb import db
# # from app.services.auth_service import get_current_user_optional, get_current_user
# # from app.services import google_drive_service
# # from app.tasks.telegram_uploader_task import transfer_to_telegram, finalize_and_delete

# # router = APIRouter()
# # ws_router = APIRouter()

# # @router.post("/upload/initiate", response_model=dict)
# # async def initiate_upload(
# #     request: InitiateUploadRequest,
# #     current_user: Optional[UserInDB] = Depends(get_current_user_optional)
# # ):
# #     file_id = str(uuid.uuid4())
# #     try:
# #         gdrive_upload_url = google_drive_service.create_resumable_upload_session(
# #             filename=request.filename,
# #             filesize=request.size
# #         )
# #     except Exception as e:
# #         print(f"!!! FAILED to create Google Drive resumable session: {e}")
# #         raise HTTPException(status_code=503, detail="Cloud storage service is currently unavailable.")

# #     file_meta = FileMetadataCreate(
# #         _id=file_id,
# #         filename=request.filename,
# #         size_bytes=request.size,
# #         content_type=request.content_type,
# #         owner_id=current_user.id if current_user else None,
# #         status=UploadStatus.PENDING
# #     )
# #     db.files.insert_one(file_meta.model_dump(by_alias=True))
# #     return {"file_id": file_id, "gdrive_upload_url": gdrive_upload_url}


# # # --- THIS IS THE DEFINITIVE FIX (BACKEND) ---
# # # The route is now simpler, and gdrive_url is a query parameter.
# # @ws_router.websocket("/ws/upload/{file_id}")
# # async def websocket_upload_proxy(
# #     websocket: WebSocket,
# #     file_id: str,
# #     gdrive_url: str  # FastAPI automatically treats this as a query parameter
# # ):
# #     await websocket.accept()
    
# #     file_doc = db.files.find_one({"_id": file_id})
# #     if not file_doc:
# #         await websocket.close(code=1008, reason="File ID not found")
# #         return

# #     if not gdrive_url:
# #         await websocket.close(code=1008, reason="gdrive_url query parameter is missing.")
# #         return

# #     total_size = file_doc.get("size_bytes", 0)
# #     bytes_sent = 0

# #     async with httpx.AsyncClient(timeout=None) as client:
# #         try:
# #             db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.UPLOADING_TO_DRIVE}})
            
# #             while True:
# #                 message = await websocket.receive()
# #                 chunk = message.get("bytes")
                
# #                 if not chunk:
# #                     if "text" in message and message["text"] == "DONE":
# #                         break
# #                     continue
                
# #                 start_byte = bytes_sent
# #                 end_byte = bytes_sent + len(chunk) - 1
# #                 headers = {
# #                     'Content-Length': str(len(chunk)),
# #                     'Content-Range': f'bytes {start_byte}-{end_byte}/{total_size}'
# #                 }
                
# #                 # We use the gdrive_url from the query parameter here
# #                 response = await client.put(gdrive_url, content=chunk, headers=headers)
                
# #                 if response.status_code not in [200, 201, 308]:
# #                     error_detail = f"Google Drive API Error: {response.text}"
# #                     print(f"!!! [{file_id}] {error_detail}")
# #                     raise HTTPException(status_code=response.status_code, detail=error_detail)

# #                 bytes_sent += len(chunk)
# #                 percentage = int((bytes_sent / total_size) * 100)
# #                 await websocket.send_json({"type": "progress", "value": percentage})

# #             if response.status_code not in [200, 201]:
# #                  raise Exception(f"Final Google Drive response was not successful: Status {response.status_code}")
                 
# #             gdrive_response_data = response.json()
# #             gdrive_id = gdrive_response_data.get('id')

# #             if not gdrive_id:
# #                 raise Exception("Upload to Google Drive succeeded, but no file ID was returned.")

# #             print(f"[{file_id}] GDrive upload successful. GDrive ID: {gdrive_id}")

# #             db.files.update_one(
# #                 {"_id": file_id},
# #                 {"$set": {
# #                     "gdrive_id": gdrive_id,
# #                     "status": UploadStatus.COMPLETED,
# #                     "storage_location": StorageLocation.GDRIVE 
# #                 }}
# #             )

# #             download_path = f"/api/v1/download/stream/{file_id}"
# #             await websocket.send_json({"type": "success", "value": download_path})
            
# #             print(f"[{file_id}] Dispatching silent Telegram archival task chain.")
# #             task_chain = chain(
# #                 transfer_to_telegram.s(gdrive_id=gdrive_id, file_id=file_id),
# #                 finalize_and_delete.s(file_id=file_id, gdrive_id=gdrive_id)
# #             )
# #             task_chain.delay()

# #         except (WebSocketDisconnect, RuntimeError, httpx.RequestError, HTTPException, Exception) as e:
# #             print(f"!!! [{file_id}] Upload proxy failed: {e}")
# #             db.files.update_one({"_id": file_id}, {"$set": {"status": UploadStatus.FAILED}})
# #             try:
# #                  await websocket.send_json({"type": "error", "value": "Upload failed. Please try again."})
# #             except RuntimeError:
# #                 pass
# #         finally:
# #             if websocket.client_state != "DISCONNECTED":
# #                 await websocket.close()
# #             print(f"[{file_id}] WebSocket proxy connection closed for file_id.")

# # @router.get("/files/{file_id}", response_model=FileMetadataInDB)
# # async def get_file_metadata(file_id: str):
# #     file_doc = db.files.find_one({"_id": file_id})
# #     if not file_doc:
# #         raise HTTPException(status_code=404, detail="File not found")
# #     return FileMetadataInDB(**file_doc)

# # @router.get("/files/me/history", response_model=list[FileMetadataInDB])
# # async def get_user_file_history(current_user: UserInDB = Depends(get_current_user)):
# #     files = db.files.find({"owner_id": current_user.id})
# #     return [FileMetadataInDB(**f) for f in files]



# # In file: Backend/app/api/v1/routes_upload.py

# import uuid
# from typing import Optional

# # --- MODIFIED: Imports are now simpler ---
# from fastapi import APIRouter, HTTPException, Depends
# from app.models.file import FileMetadataCreate, FileMetadataInDB, InitiateUploadRequest, UploadStatus
# from app.models.user import UserInDB
# from app.db.mongodb import db
# from app.services.auth_service import get_current_user_optional, get_current_user
# from app.services import google_drive_service
# from datetime import datetime
# from app.ws_manager import manager

# # --- MODIFIED: Only one router is needed in this file now ---
# router = APIRouter()
# # ws_router has been removed.

# @router.post("/upload/initiate", response_model=dict)
# async def initiate_upload(
#     request: InitiateUploadRequest,
#     current_user: Optional[UserInDB] = Depends(get_current_user_optional)
# ):
#     file_id = str(uuid.uuid4())
#     try:
#         gdrive_upload_url = google_drive_service.create_resumable_upload_session(
#             filename=request.filename,
#             filesize=request.size
#         )
#     except Exception as e:
#         print(f"!!! FAILED to create Google Drive resumable session: {e}")
#         raise HTTPException(status_code=503, detail="Cloud storage service is currently unavailable.")
#     # ADD THIS BROADCAST
#     timestamp = datetime.utcnow().isoformat()
#     await manager.broadcast(f"[{timestamp}] [API_REQUEST] Google Drive: Initiate Resumable Upload for '{request.filename}'") 

#     file_meta = FileMetadataCreate(
#         _id=file_id,
#         filename=request.filename,
#         size_bytes=request.size,
#         content_type=request.content_type,
#         owner_id=current_user.id if current_user else None,
#         status=UploadStatus.PENDING
#     )
#     db.files.insert_one(file_meta.model_dump(by_alias=True))
#     return {"file_id": file_id, "gdrive_upload_url": gdrive_upload_url}

# # --- REMOVED: The entire websocket_upload_proxy function has been moved to main.py ---

# # --- These HTTP routes remain the same ---
# @router.get("/files/{file_id}", response_model=FileMetadataInDB)
# async def get_file_metadata(file_id: str):
#     file_doc = db.files.find_one({"_id": file_id})
#     if not file_doc:
#         raise HTTPException(status_code=404, detail="File not found")
#     return FileMetadataInDB(**file_doc)

# @router.get("/files/me/history", response_model=list[FileMetadataInDB])
# async def get_user_file_history(current_user: UserInDB = Depends(get_current_user)):
#     files = db.files.find({"owner_id": current_user.id})
#     return [FileMetadataInDB(**f) for f in files]



# In file: Backend/app/api/v1/routes_upload.py

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from app.models.file import FileMetadataCreate, FileMetadataInDB, InitiateUploadRequest, UploadStatus
from app.models.user import UserInDB
from app.db.mongodb import db
from app.services.auth_service import get_current_user_optional, get_current_user
# --- MODIFIED: Import the pool manager instead of the whole service ---
from app.services.google_drive_service import gdrive_pool_manager, create_resumable_upload_session
from datetime import datetime
# from app.ws_manager import manager # Assuming you have a WebSocket manager for admin logs

router = APIRouter()

from fastapi import Request
from app.services.rate_limiter import rate_limiter

@router.post("/upload/initiate", response_model=dict)
async def initiate_upload(
    request: InitiateUploadRequest,
    client_request: Request,  # ADD THIS
    current_user: Optional[UserInDB] = Depends(get_current_user_optional)
):
    file_id = str(uuid.uuid4())
    
    # GET CLIENT IP
    client_ip = client_request.client.host
    
    # CHECK UPLOAD SIZE LIMIT (2GB per upload)
    size_allowed, size_message = await rate_limiter.check_upload_size_limit(request.size)
    if not size_allowed:
        raise HTTPException(status_code=413, detail=size_message)
    
    # CHECK RATE LIMIT INSTEAD OF USER QUOTA
    allowed, message = await rate_limiter.check_rate_limit(client_ip, request.size)
    if not allowed:
        raise HTTPException(status_code=429, detail=message)
    
    # --- NEW: Get an active account from the pool ---
    active_account = await gdrive_pool_manager.get_active_account()
    if not active_account:
        raise HTTPException(status_code=503, detail="All storage accounts are currently busy or unavailable. Please try again in a minute.")

    try:
        # --- MODIFIED: Pass the active account to the session creator ---
        gdrive_upload_url = create_resumable_upload_session(
            filename=request.filename,
            filesize=request.size,
            account=active_account
        )
    except Exception as e:
        print(f"!!! FAILED to create Google Drive resumable session: {e}")
        raise HTTPException(status_code=503, detail="Cloud storage service is currently unavailable.")
    
    # --- NEW: Increment the upload volume for the chosen account ---
    gdrive_pool_manager.tracker.increment_upload_volume(active_account.id, request.size)

    # timestamp = datetime.utcnow().isoformat()
    # await manager.broadcast(f"[{timestamp}] [API_REQUEST] Google Drive: Initiate Resumable Upload for '{request.filename}'") 

    file_meta = FileMetadataCreate(
        _id=file_id,
        filename=request.filename,
        size_bytes=request.size,
        content_type=request.content_type,
        owner_id=current_user.id if current_user else None,
        status=UploadStatus.PENDING,
        # --- NEW: Save which account was used ---
        gdrive_account_id=active_account.id
    )
    db.files.insert_one(file_meta.model_dump(by_alias=True))
    return {"file_id": file_id, "gdrive_upload_url": gdrive_upload_url}

# --- HTTP routes for metadata/history remain the same ---
@router.get("/files/{file_id}", response_model=FileMetadataInDB)
async def get_file_metadata(file_id: str):
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")
    return FileMetadataInDB(**file_doc)

@router.get("/files/me/history", response_model=list[FileMetadataInDB])
async def get_user_file_history(current_user: UserInDB = Depends(get_current_user)):
    files = db.files.find({"owner_id": current_user.id})
    return [FileMetadataInDB(**f) for f in files]