# In file: Backend/app/api/v1/routes_upload.py

import uuid
import logging
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

# Configure upload logging
upload_logger = logging.getLogger('directdrive.upload')

@router.post("/upload/initiate", response_model=dict)
async def initiate_upload(
    request: InitiateUploadRequest,
    client_request: Request,
    current_user: Optional[UserInDB] = Depends(get_current_user_optional)
):
    file_id = str(uuid.uuid4())
    
    # GET CLIENT IP
    client_ip = client_request.client.host
    
    # Log upload initiation with user context
    user_type = "authenticated" if current_user else "anonymous"
    user_id = current_user.email if current_user else client_ip
    upload_logger.info(f"Upload initiate - User: {user_id}, Type: {user_type}, File: {request.filename}, Size: {request.size} bytes")
    
    # ENHANCED RATE LIMITING - Differentiate between authenticated and anonymous users
    if current_user:
        # Authenticated users: Use email-based tracking with higher limits
        upload_logger.info(f"Using authenticated rate limiting for user: {current_user.email}")
        
        # Check authenticated rate limits (typically 10GB, 5 concurrent uploads)
        rate_allowed, rate_message = await rate_limiter.check_authenticated_rate_limit(
            current_user.email, request.size, current_user.storage_limit_bytes
        )
        
        # Additional check: User's actual storage quota vs current usage
        quota_allowed, quota_message = await rate_limiter.check_user_storage_quota(
            current_user.email, request.size, current_user.storage_used_bytes, current_user.storage_limit_bytes
        )
        
        # Check upload size limit for authenticated users
        size_allowed, size_message = await rate_limiter.check_authenticated_upload_size_limit(
            request.size, current_user.storage_limit_bytes
        )
        
        if not rate_allowed:
            upload_logger.warning(f"Rate limit failed for user {current_user.email}: {rate_message}")
            raise HTTPException(status_code=429, detail=rate_message)
        
        if not quota_allowed:
            upload_logger.warning(f"Storage quota exceeded for user {current_user.email}: {quota_message}")
            raise HTTPException(status_code=413, detail=quota_message)
        
        if not size_allowed:
            upload_logger.warning(f"File size limit exceeded for user {current_user.email}: {size_message}")
            raise HTTPException(status_code=413, detail=size_message)
            
    else:
        # Anonymous users: Use IP-based tracking with lower limits (2GB, 3 concurrent)
        upload_logger.info(f"Using anonymous rate limiting for IP: {client_ip}")
        
        # Check upload size limit for anonymous users (2GB)
        size_allowed, size_message = await rate_limiter.check_upload_size_limit(request.size)
        if not size_allowed:
            upload_logger.warning(f"Size limit exceeded for anonymous IP {client_ip}: {size_message}")
            raise HTTPException(status_code=413, detail=size_message)
        
        # Check rate limit for anonymous users
        rate_allowed, rate_message = await rate_limiter.check_rate_limit(client_ip, request.size)
        if not rate_allowed:
            upload_logger.warning(f"Rate limit exceeded for anonymous IP {client_ip}: {rate_message}")
            raise HTTPException(status_code=429, detail=rate_message)
    
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

    # Store file metadata with owner information
    file_meta = FileMetadataCreate(
        _id=file_id,
        filename=request.filename,
        size_bytes=request.size,
        content_type=request.content_type,
        owner_id=current_user.email if current_user else None,  # Use email as owner_id for consistency
        status=UploadStatus.PENDING,
        # --- NEW: Save which account was used ---
        gdrive_account_id=active_account.id
    )
    db.files.insert_one(file_meta.model_dump(by_alias=True))
    
    upload_logger.info(f"Upload session created successfully - File ID: {file_id}, User: {user_id}, Account: {active_account.id}")
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