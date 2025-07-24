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
    current_user: Optional[UserInDB] = Depends(get_current_user_optional)
):
    # --- NEW: Get an active account from the pool for the entire batch ---
    active_account = await gdrive_pool_manager.get_active_account()
    if not active_account:
        raise HTTPException(status_code=503, detail="All storage accounts are currently busy or unavailable. Please try again in a minute.")

    batch_id = str(uuid.uuid4())
    file_upload_info_list = []
    file_ids_for_batch = []
    total_batch_size = 0

    for file_info in request.files:
        file_id = str(uuid.uuid4())
        total_batch_size += file_info.size

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
    zip_filename = f"batch_{batch_id}.zip"
    headers = {
        'Content-Disposition': f'attachment; filename="{zip_filename}"'
    }
    # The zipping service will now need to handle getting the right account for each file
    return StreamingResponse(
        zipping_service.stream_zip_archive(batch_id),
        media_type="application/zip",
        headers=headers
    )