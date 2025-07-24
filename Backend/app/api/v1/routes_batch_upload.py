# File: Backend/app/api/v1/routes_batch_upload.py

import uuid
from typing import Optional, List
from fastapi.responses import StreamingResponse
from fastapi import APIRouter, HTTPException, Depends, Request

# Models for our new batch functionality and for existing files/users
from app.models.batch import BatchMetadata, InitiateBatchRequest, InitiateBatchResponse
from app.models.file import FileMetadataCreate, UploadStatus, FileMetadataInDB
from app.models.user import UserInDB

# Database access and other services
from app.db.mongodb import db
from app.services.auth_service import get_current_user_optional
from app.services import google_drive_service
from app.services import zipping_service
from app.services.rate_limiter import rate_limiter

# This new router will handle all API calls related to batch processing.
router = APIRouter()


# @router.post("/initiate", response_model=InitiateBatchResponse)
# async def initiate_batch_upload(
#     request: InitiateBatchRequest,
#     current_user: Optional[UserInDB] = Depends(get_current_user_optional)
# ):
#     """
#     NEW BATCH FLOW - Step 1:
#     - Frontend sends a list of files it intends to upload.
#     - Backend creates a single unique `batch_id`.
#     - Backend loops through the file list:
#         - For each file, it creates a unique `file_id`.
#         - It contacts Google Drive to get a resumable upload session URL.
#         - It creates an individual DB record for the file, linking it to the batch.
#     - Backend creates the main batch DB record.
#     - Finally, it returns the `batch_id` and a list of all `file_id`s and their
#       corresponding GDrive URLs for the frontend to use.
#     """
#     batch_id = str(uuid.uuid4())
#     file_upload_info_list = []
#     file_ids_for_batch = []

#     # 1. Process each file in the request
#     for file_info in request.files:
#         file_id = str(uuid.uuid4())

#         try:
#             # Get the unique, one-time upload URL from Google Drive
#             gdrive_upload_url = google_drive_service.create_resumable_upload_session(
#                 filename=file_info.filename,
#                 filesize=file_info.size
#             )
#         except Exception as e:
#             print(f"!!! FAILED to create Google Drive resumable session for {file_info.filename}: {e}")
#             # If even one file fails to get a session URL, we fail the entire batch request.
#             raise HTTPException(status_code=503, detail=f"Cloud storage service is currently unavailable for file: {file_info.filename}")

#         # 2. Create the individual file metadata record in the 'files' collection
#         owner_id = current_user.id if current_user else None
#         file_meta = FileMetadataCreate(
#             _id=file_id,
#             filename=file_info.filename,
#             size_bytes=file_info.size,
#             content_type=file_info.content_type,
#             owner_id=owner_id,
#             status=UploadStatus.PENDING,
#             batch_id=batch_id  # Link this file to our new batch
#         )
#         db.files.insert_one(file_meta.model_dump(by_alias=True))

#         # 3. Add the file's details to the list we'll return to the frontend
#         file_upload_info_list.append(
#             InitiateBatchResponse.FileUploadInfo(
#                 file_id=file_id,
#                 gdrive_upload_url=gdrive_upload_url,
#                 original_filename=file_info.filename
#             )
#         )
#         file_ids_for_batch.append(file_id)

#     # 4. Create the main batch record in the 'batches' collection
#     owner_id = current_user.id if current_user else None
#     batch_meta = BatchMetadata(
#         _id=batch_id,
#         file_ids=file_ids_for_batch,
#         owner_id=owner_id
#     )
#     db.batches.insert_one(batch_meta.model_dump(by_alias=True))

#     print(f"[BATCH_UPLOAD] Initiated batch {batch_id} with {len(file_ids_for_batch)} files.")

#     # 5. Return the complete response to the frontend
#     return InitiateBatchResponse(
#         batch_id=batch_id,
#         files=file_upload_info_list
#     )
    
    
    
    
# @router.get("/{batch_id}", response_model=List[FileMetadataInDB])
# async def get_batch_files_metadata(batch_id: str):
#     """
#     Retrieves the metadata for all files associated with a given batch ID.
#     The download page will call this to display the list of files.
#     """
#     # First, check if the batch itself exists to prevent scanning for non-existent batches.
#     batch_doc = db.batches.find_one({"_id": batch_id})
#     if not batch_doc:
#         raise HTTPException(status_code=404, detail="Batch not found")
    
#     # Query the 'files' collection for all documents with the matching batch_id
#     file_docs_cursor = db.files.find({"batch_id": batch_id})
    
#     # Convert cursor to a list of dictionaries
#     files_list = [file for file in file_docs_cursor]
    
#     if not files_list:
#         # This case could happen if the batch was created but file records failed.
#         raise HTTPException(status_code=404, detail="No files found for this batch")

#     return files_list



# # In file: Backend/app/api/v1/routes_batch_upload.py

# # ... (@router.get("/{batch_id}", ...)) unchanged

# # --- V V V --- ADD THE NEW ENDPOINT BELOW --- V V V ---

# @router.get("/download-zip/{batch_id}")
# async def download_batch_as_zip(batch_id: str):
#     """
#     Fetches all files in a batch, creates a zip archive in memory,
#     and streams it back to the client.
#     """
#     # Define headers for the response
#     zip_filename = f"batch_{batch_id}.zip"
#     headers = {
#         'Content-Disposition': f'attachment; filename="{zip_filename}"'
#     }

#     # Return a streaming response that uses our zipping service generator
#     return StreamingResponse(
#         zipping_service.stream_zip_archive(batch_id),
#         media_type="application/zip",
#         headers=headers
#     )



# File: Backend/app/api/v1/routes_batch_upload.py

import uuid
from typing import Optional, List
from fastapi.responses import StreamingResponse
from fastapi import APIRouter, HTTPException, Depends

from app.models.batch import BatchMetadata, InitiateBatchRequest, InitiateBatchResponse
from app.models.file import FileMetadataCreate, UploadStatus, FileMetadataInDB
from app.models.user import UserInDB
from app.db.mongodb import db
from app.services.auth_service import get_current_user_optional
# --- MODIFIED: Import the pool manager and helper functions ---
from app.services.google_drive_service import gdrive_pool_manager, create_resumable_upload_session
from app.services import zipping_service

router = APIRouter()

@router.post("/initiate", response_model=InitiateBatchResponse)
async def initiate_batch_upload(
    request: InitiateBatchRequest,
    client_request: Request,
    current_user: Optional[UserInDB] = Depends(get_current_user_optional)
):
    # GET CLIENT IP
    client_ip = client_request.client.host
    
    # CHECK BATCH UPLOAD SIZE LIMIT - Dynamic based on authentication
    # Authenticated users: 10GB, Anonymous users: 2GB
    file_sizes = [file_info.size for file_info in request.files]
    if current_user:
        max_size = 10737418240  # 10GB for authenticated users
        batch_size_allowed, batch_size_message = await rate_limiter.check_authenticated_batch_upload_size_limit(file_sizes, max_size)
    else:
        batch_size_allowed, batch_size_message = await rate_limiter.check_batch_upload_size_limit(file_sizes)
    
    if not batch_size_allowed:
        raise HTTPException(status_code=413, detail=batch_size_message)
    
    # Calculate total batch size for rate limiting
    total_batch_size = sum(file_sizes)
    
    # CHECK RATE LIMIT FOR BATCH UPLOAD
    allowed, message = await rate_limiter.check_rate_limit(client_ip, total_batch_size)
    if not allowed:
        raise HTTPException(status_code=429, detail=message)
    
    # --- NEW: Get an active account from the pool for the entire batch ---
    active_account = await gdrive_pool_manager.get_active_account()
    if not active_account:
        raise HTTPException(status_code=503, detail="All storage accounts are currently busy or unavailable. Please try again in a minute.")

    batch_id = str(uuid.uuid4())
    file_upload_info_list = []
    file_ids_for_batch = []

    for file_info in request.files:
        file_id = str(uuid.uuid4())

        try:
            # --- MODIFIED: Pass the same active account for every file in the batch ---
            gdrive_upload_url = create_resumable_upload_session(
                filename=file_info.filename,
                filesize=file_info.size,
                account=active_account
            )
        except Exception as e:
            print(f"!!! FAILED to create Google Drive resumable session for {file_info.filename}: {e}")
            raise HTTPException(status_code=503, detail=f"Cloud storage service is currently unavailable for file: {file_info.filename}")

        owner_id = current_user.id if current_user else None
        file_meta = FileMetadataCreate(
            _id=file_id,
            filename=file_info.filename,
            size_bytes=file_info.size,
            content_type=file_info.content_type,
            owner_id=owner_id,
            status=UploadStatus.PENDING,
            batch_id=batch_id,
            # --- NEW: Save which account was used ---
            gdrive_account_id=active_account.id
        )
        db.files.insert_one(file_meta.model_dump(by_alias=True))

        file_upload_info_list.append(
            InitiateBatchResponse.FileUploadInfo(
                file_id=file_id,
                gdrive_upload_url=gdrive_upload_url,
                original_filename=file_info.filename
            )
        )
        file_ids_for_batch.append(file_id)

    # --- NEW: Increment upload volume once for the whole batch ---
    gdrive_pool_manager.tracker.increment_upload_volume(active_account.id, total_batch_size)

    owner_id = current_user.id if current_user else None
    batch_meta = BatchMetadata(
        _id=batch_id,
        file_ids=file_ids_for_batch,
        owner_id=owner_id
    )
    db.batches.insert_one(batch_meta.model_dump(by_alias=True))

    print(f"[BATCH_UPLOAD] Initiated batch {batch_id} on {active_account.id} with {len(file_ids_for_batch)} files.")

    return InitiateBatchResponse(
        batch_id=batch_id,
        files=file_upload_info_list
    )

@router.get("/{batch_id}", response_model=List[FileMetadataInDB])
async def get_batch_files_metadata(batch_id: str):
    batch_doc = db.batches.find_one({"_id": batch_id})
    if not batch_doc:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    file_docs_cursor = db.files.find({"batch_id": batch_id})
    files_list = [file for file in file_docs_cursor]
    
    if not files_list:
        raise HTTPException(status_code=404, detail="No files found for this batch")
    return files_list

@router.get("/download-zip/{batch_id}")
async def download_batch_as_zip(batch_id: str):
    from app.core.concurrency_config import concurrency_manager
    
    # Verify batch exists first
    batch_doc = db.batches.find_one({"_id": batch_id})
    if not batch_doc:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Check if we can handle another ZIP operation
    can_proceed = await concurrency_manager.acquire_zip_slot(batch_id)
    if not can_proceed:
        raise HTTPException(
            status_code=503, 
            detail="Server is currently busy processing other ZIP downloads. Please try again in a few minutes."
        )
    
    zip_filename = f"batch_{batch_id}.zip"
    headers = {
        'Content-Disposition': f'attachment; filename="{zip_filename}"',
        'Content-Type': 'application/zip',
        'Cache-Control': 'no-cache',
        'Accept-Ranges': 'bytes',
        'Connection': 'keep-alive'
    }
    
    async def controlled_zip_stream():
        """Wrapper that ensures proper cleanup of concurrency slot"""
        try:
            async for chunk in zipping_service.stream_zip_archive(batch_id):
                yield chunk
        finally:
            # Always release the slot when done
            concurrency_manager.release_zip_slot(batch_id)
    
    return StreamingResponse(
        controlled_zip_stream(),
        media_type="application/zip",
        headers=headers
    )