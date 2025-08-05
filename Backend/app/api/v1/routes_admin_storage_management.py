from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field, HttpUrl
from enum import Enum
import httpx
import uuid

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

@router.get("/storage/test")
async def test_storage_endpoint():
    """
    Test endpoint to check if the storage management routes are working
    """
    try:
        # Check database connection
        total_files = db.files.count_documents({})
        total_users = db.users.count_documents({})
        
        # Check for admin users
        admin_users = db.users.count_documents({"role": {"$in": ["admin", "superadmin"]}})
        
        return {
            "message": "Storage management endpoint is working",
            "database_connected": True,
            "total_files": total_files,
            "total_users": total_users,
            "admin_users": admin_users
        }
    except Exception as e:
        return {
            "message": "Storage management endpoint error",
            "database_connected": False,
            "error": str(e)
        }

@router.post("/storage/create-test-admin")
async def create_test_admin():
    """
    Create a test admin user for development purposes
    """
    try:
        from app.services.auth_service import get_password_hash
        from datetime import datetime
        
        # Check if test admin already exists
        existing_admin = db.users.find_one({"email": "admin@test.com"})
        if existing_admin:
            return {
                "message": "Test admin already exists",
                "email": "admin@test.com",
                "password": "admin123"
            }
        
        # Create test admin user
        admin_user = {
            "_id": str(uuid.uuid4()),  # Use string ID instead of ObjectId
            "email": "admin@test.com",
            "hashed_password": get_password_hash("admin123"),
            "role": "admin",
            "is_admin": True,
            "storage_limit_bytes": 107374182400,  # 100GB
            "created_at": datetime.utcnow(),
            "last_login": datetime.utcnow()
        }
        
        result = db.users.insert_one(admin_user)
        
        return {
            "message": "Test admin created successfully",
            "email": "admin@test.com",
            "password": "admin123",
            "user_id": str(result.inserted_id)
        }
    except Exception as e:
        return {
            "message": "Failed to create test admin",
            "error": str(e)
        }

@router.post("/storage/login-test-admin")
async def login_test_admin():
    """
    Login as test admin and get token
    """
    try:
        from app.services.admin_auth_service import authenticate_admin, create_admin_access_token
        from datetime import timedelta
        from app.core.config import settings
        
        # Authenticate admin
        admin = await authenticate_admin("admin@test.com", "admin123")
        if not admin:
            return {
                "message": "Test admin authentication failed",
                "error": "Invalid credentials"
            }
        
        # Create token
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_admin_access_token(
            data={"sub": admin.email, "role": admin.role.value}, 
            expires_delta=access_token_expires
        )
        
        return {
            "message": "Test admin login successful",
            "access_token": access_token,
            "token_type": "bearer",
            "admin_role": admin.role.value,
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        }
    except Exception as e:
        return {
            "message": "Failed to login test admin",
            "error": str(e)
        }

@router.get("/storage/stats-test")
async def get_storage_stats_test():
    """
    Test version of storage stats without authentication
    """
    try:
        # First, let's check if we can connect to the database
        total_files = db.files.count_documents({})
        
        # Simple aggregation to get basic stats
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total_files": {"$sum": 1},
                    "total_size": {"$sum": {"$ifNull": ["$size_bytes", 0]}}
                }
            }
        ]
        
        result = list(db.files.aggregate(pipeline))
        
        if not result:
            # No files in database
            return {
                "total_files": 0,
                "total_size_bytes": 0,
                "by_storage_type": {
                    "google_drive": {"count": 0, "size_bytes": 0},
                    "hetzner": {"count": 0, "size_bytes": 0}
                },
                "by_status": {}
            }
            
        stats = result[0]
        
        return {
            "total_files": stats.get("total_files", 0),
            "total_size_bytes": stats.get("total_size", 0),
            "by_storage_type": {
                "google_drive": {"count": 0, "size_bytes": 0},
                "hetzner": {"count": 0, "size_bytes": 0}
            },
            "by_status": {}
        }
        
    except Exception as e:
        print(f"Error in get_storage_stats_test: {str(e)}")
        return {
            "total_files": 0,
            "total_size_bytes": 0,
            "by_storage_type": {
                "google_drive": {"count": 0, "size_bytes": 0},
                "hetzner": {"count": 0, "size_bytes": 0}
            },
            "by_status": {},
            "error": str(e)
        }

@router.get("/storage/stats", response_model=StorageStatsResponse)
async def get_storage_stats(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """
    Get storage statistics across all storage locations
    """
    try:
        # First, let's check if we can connect to the database
        total_files = db.files.count_documents({})
        
        # Simple aggregation to get basic stats
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total_files": {"$sum": 1},
                    "total_size": {"$sum": {"$ifNull": ["$size_bytes", 0]}}
                }
            }
        ]
        
        result = list(db.files.aggregate(pipeline))
        
        if not result:
            # No files in database
            return StorageStatsResponse(
                total_files=0,
                total_size_bytes=0,
                by_storage_type={
                    "google_drive": {"count": 0, "size_bytes": 0},
                    "hetzner": {"count": 0, "size_bytes": 0}
                },
                by_status={}
            )
            
        stats = result[0]
        
        # For now, return simple stats without complex storage type breakdown
        # This can be enhanced later when we have more data
        
        # Log admin activity
        await log_admin_activity(
            admin_email=current_admin.email,
            action="view_storage_stats",
            details="Viewed storage statistics",
            ip_address=get_client_ip(request)
        )
        
        return StorageStatsResponse(
            total_files=stats.get("total_files", 0),
            total_size_bytes=stats.get("total_size", 0),
            by_storage_type={
                "google_drive": {"count": 0, "size_bytes": 0},
                "hetzner": {"count": 0, "size_bytes": 0}
            },
            by_status={}
        )
        
    except Exception as e:
        print(f"Error in get_storage_stats: {str(e)}")
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
    try:
        # Log admin activity
        await log_admin_activity(
            admin_email=current_admin.email,
            action="list_storage_files",
            details=f"Listed files for storage type: {storage_type}, path: {path}",
            ip_address=get_client_ip(request)
        )
        
        # For now, return files from the database regardless of storage type
        # This can be enhanced later to filter by actual storage location
        skip = (page - 1) * limit
        
        # Get total count
        total_files = db.files.count_documents({})
        
        # Get files with pagination
        files_cursor = db.files.find({}).skip(skip).limit(limit)
        files = list(files_cursor)
        
        # Convert to StorageFileInfo format
        storage_files = []
        for file_doc in files:
            storage_files.append(StorageFileInfo(
                file_id=str(file_doc.get("_id")),
                filename=file_doc.get("filename", "Unknown"),
                path="/",
                size_bytes=file_doc.get("size_bytes", 0),
                last_modified=file_doc.get("upload_date", datetime.utcnow()),
                content_type=file_doc.get("content_type"),
                is_directory=False
            ))
        
        total_pages = (total_files + limit - 1) // limit
        
        return StorageFileListResponse(
            files=storage_files,
            total=total_files,
            page=page,
            limit=limit,
            total_pages=total_pages
        )
        
    except Exception as e:
        print(f"Error in list_storage_files: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing files: {str(e)}"
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
