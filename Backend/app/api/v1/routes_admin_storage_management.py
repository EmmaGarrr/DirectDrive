from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field, HttpUrl
from enum import Enum
import httpx

from app.services.admin_auth_service import get_current_admin, log_admin_activity, get_client_ip
from app.models.admin import AdminUserInDB
from app.models.file import FileMetadataInDB, FileStorageStatus, FileStorageInfo
from app.db.mongodb import db
from app.services import google_drive_service, hetzner_service
from app.core.config import settings

router = APIRouter()

# ================================
# MODELS
# ================================

class StorageType(str, Enum):
    GOOGLE_DRIVE = "google_drive"
    HETZNER = "hetzner"

class FileStorageStatusResponse(BaseModel):
    file_id: str
    filename: str
    storage_type: StorageType
    status: FileStorageStatus
    last_checked: datetime
    size_bytes: Optional[int] = None
    last_modified: Optional[datetime] = None
    error: Optional[str] = None
    url: Optional[HttpUrl] = None

class StorageStatsResponse(BaseModel):
    total_files: int
    total_size_bytes: int
    by_storage_type: Dict[str, Dict[str, Any]]
    by_status: Dict[str, int]

class StorageFileInfo(BaseModel):
    file_id: str
    filename: str
    path: str
    size_bytes: int
    last_modified: datetime
    content_type: Optional[str] = None
    is_directory: bool = False

class StorageFileListResponse(BaseModel):
    files: List[StorageFileInfo]
    total: int
    page: int
    limit: int
    total_pages: int

# ================================
# ENDPOINTS
# ================================

@router.get("/storage/files/status/{file_id}", response_model=Dict[str, FileStorageStatusResponse])
async def get_file_storage_status(
    file_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """
    Get storage status for a file across all storage locations
    """
    # Get file metadata from database
    file_doc = await db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")
    
    file_metadata = FileMetadataInDB(**file_doc)
    response = {}
    
    # Check Google Drive status if available
    if file_metadata.gdrive_info:
        try:
            gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(
                file_metadata.gdrive_info.account_id
            )
            if gdrive_account:
                gdrive_info = await google_drive_service.get_file_info(
                    file_metadata.gdrive_info.file_id,
                    gdrive_account
                )
                response["google_drive"] = FileStorageStatusResponse(
                    file_id=file_metadata.gdrive_info.file_id,
                    filename=file_metadata.filename,
                    storage_type=StorageType.GOOGLE_DRIVE,
                    status=file_metadata.gdrive_info.status,
                    last_checked=datetime.utcnow(),
                    size_bytes=gdrive_info.get('size'),
                    last_modified=datetime.fromisoformat(gdrive_info['modified_time']) if gdrive_info.get('modified_time') else None,
                    error=file_metadata.gdrive_info.error,
                    url=gdrive_info.get('web_view_link')
                )
        except Exception as e:
            response["google_drive"] = FileStorageStatusResponse(
                file_id=file_metadata.gdrive_info.file_id if file_metadata.gdrive_info else "unknown",
                filename=file_metadata.filename,
                storage_type=StorageType.GOOGLE_DRIVE,
                status=FileStorageStatus.ERROR,
                last_checked=datetime.utcnow(),
                error=f"Error checking Google Drive: {str(e)}"
            )
    
    # Check Hetzner status if available
    if file_metadata.hetzner_info and file_metadata.hetzner_info.path:
        try:
            hetzner_info = await hetzner_service.get_file_info(file_metadata.hetzner_info.path)
            response["hetzner"] = FileStorageStatusResponse(
                file_id=file_metadata.hetzner_info.file_id or file_id,
                filename=file_metadata.filename,
                storage_type=StorageType.HETZNER,
                status=file_metadata.hetzner_info.status,
                last_checked=datetime.utcnow(),
                size_bytes=hetzner_info.get('size'),
                last_modified=datetime.fromisoformat(hetzner_info['last_modified']) if hetzner_info.get('last_modified') else None,
                error=file_metadata.hetzner_info.error,
                url=hetzner_info.get('url')
            )
        except Exception as e:
            response["hetzner"] = FileStorageStatusResponse(
                file_id=file_metadata.hetzner_info.file_id if file_metadata.hetzner_info else "unknown",
                filename=file_metadata.filename,
                storage_type=StorageType.HETZNER,
                status=FileStorageStatus.ERROR,
                last_checked=datetime.utcnow(),
                error=f"Error checking Hetzner: {str(e)}"
            )
    
    # Log admin activity
    await log_admin_activity(
        admin_id=current_admin.id,
        action="view_file_storage_status",
        details={"file_id": file_id},
        ip_address=get_client_ip(request)
    )
    
    return response

@router.get("/storage/stats", response_model=StorageStatsResponse)
async def get_storage_stats(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """
    Get storage statistics across all storage locations
    """
    # Get stats from database
    pipeline = [
        {
            "$group": {
                "_id": None,
                "total_files": {"$sum": 1},
                "total_size": {"$sum": "$size_bytes"},
                "by_storage": {
                    "$push": {
                        "gdrive": {"$cond": [{"$ifNull": ["$gdrive_info", False]}, 1, 0]},
                        "hetzner": {"$cond": [{"$ifNull": ["$hetzner_info", False]}, 1, 0]}
                    }
                },
                "by_status": {"$push": {
                    "gdrive_status": "$gdrive_info.status",
                    "hetzner_status": "$hetzner_info.status"
                }}
            }
        }
    ]
    
    try:
        result = await db.files.aggregate(pipeline).to_list(1)
        if not result:
            return StorageStatsResponse(
                total_files=0,
                total_size_bytes=0,
                by_storage_type={},
                by_status={}
            )
            
        stats = result[0]
        
        # Process storage type distribution
        by_storage = {
            "google_drive": {"count": 0, "size_bytes": 0},
            "hetzner": {"count": 0, "size_bytes": 0}
        }
        
        # Process status distribution
        status_counts = {}
        for status_doc in stats.get("by_status", []):
            for storage, status_val in status_doc.items():
                if status_val:
                    status_key = f"{storage.split('_')[0]}_{status_val.lower()}"
                    status_counts[status_key] = status_counts.get(status_key, 0) + 1
        
        # Log admin activity
        await log_admin_activity(
            admin_id=current_admin.id,
            action="view_storage_stats",
            details={},
            ip_address=get_client_ip(request)
        )
        
        return StorageStatsResponse(
            total_files=stats["total_files"],
            total_size_bytes=stats["total_size"],
            by_storage_type=by_storage,
            by_status=status_counts
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating storage stats: {str(e)}"
        )

@router.get("/storage/files/{storage_type}", response_model=StorageFileListResponse)
async def list_storage_files(
    storage_type: StorageType,
    request: Request,
    path: str = Query("/"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """
    List files in a storage location
    """
    if storage_type == StorageType.GOOGLE_DRIVE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google Drive file listing is not implemented yet"
        )
    
    elif storage_type == StorageType.HETZNER:
        try:
            # For Hetzner, we can list files in a directory
            # Note: This is a simplified implementation - actual implementation would use WebDAV PROPFIND
            # to list directory contents
            
            # Log admin activity
            await log_admin_activity(
                admin_id=current_admin.id,
                action="list_storage_files",
                details={"storage_type": storage_type, "path": path},
                ip_address=get_client_ip(request)
            )
            
            # In a real implementation, this would make actual API calls to Hetzner
            # For now, return a mock response
            return StorageFileListResponse(
                files=[],
                total=0,
                page=page,
                limit=limit,
                total_pages=0
            )
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error listing Hetzner files: {str(e)}"
            )
    
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported storage type: {storage_type}"
        )

@router.delete("/storage/files/{storage_type}/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_storage_file(
    storage_type: StorageType,
    file_id: str,
    request: Request,
    force: bool = Query(False, description="Force deletion even if file is in use"),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """
    Delete a file from storage
    """
    # Log the deletion request
    await log_admin_activity(
        admin_id=current_admin.id,
        action=f"delete_from_{storage_type.value}",
        details={"file_id": file_id, "force": force},
        ip_address=get_client_ip(request)
    )
    
    try:
        if storage_type == StorageType.GOOGLE_DRIVE:
            # Get file metadata to find the account ID
            file_doc = await db.files.find_one({"gdrive_info.file_id": file_id})
            if not file_doc:
                raise HTTPException(status_code=404, detail="File not found in database")
                
            file_metadata = FileMetadataInDB(**file_doc)
            gdrive_account = google_drive_service.gdrive_pool_manager.get_account_by_id(
                file_metadata.gdrive_info.account_id
            )
            if not gdrive_account:
                raise HTTPException(status_code=400, detail="Google Drive account not found")
                
            # Delete from Google Drive
            await google_drive_service.delete_file(file_id, gdrive_account, permanent=force)
            
            # Update database
            await db.files.update_one(
                {"_id": file_metadata.id},
                {"$set": {"gdrive_info.status": FileStorageStatus.DELETED}}
            )
            
        elif storage_type == StorageType.HETZNER:
            # For Hetzner, we need the full path
            file_doc = await db.files.find_one({"hetzner_info.file_id": file_id})
            if not file_doc:
                raise HTTPException(status_code=404, detail="File not found in database")
                
            file_metadata = FileMetadataInDB(**file_doc)
            if not file_metadata.hetzner_info or not file_metadata.hetzner_info.path:
                raise HTTPException(status_code=400, detail="Hetzner path not found")
                
            # Delete from Hetzner
            await hetzner_service.delete_file(file_metadata.hetzner_info.path)
            
            # Update database
            await db.files.update_one(
                {"_id": file_metadata.id},
                {"$set": {"hetzner_info.status": FileStorageStatus.DELETED}}
            )
            
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported storage type: {storage_type}"
            )
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting file: {str(e)}"
        )
    
    return None

@router.post("/storage/sync/{file_id}", status_code=status.HTTP_202_ACCEPTED)
async def sync_file_storage(
    file_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """
    Trigger a sync of file storage status
    """
    # This would trigger a background task to check and sync the file status
    # across all storage locations
    
    # Log the sync request
    await log_admin_activity(
        admin_id=current_admin.id,
        action="sync_file_storage",
        details={"file_id": file_id},
        ip_address=get_client_ip(request)
    )
    
    return {"status": "sync_started", "file_id": file_id}
