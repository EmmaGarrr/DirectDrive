from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Response
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from app.services.admin_auth_service import get_current_admin, log_admin_activity, get_client_ip
from app.models.admin import AdminUserInDB
from app.models.file import FileMetadataInDB, StorageLocation, UploadStatus, BackupStatus
from app.db.mongodb import db
from app.services.google_drive_service import gdrive_pool_manager
from pydantic import BaseModel
import re
from bson import ObjectId
import mimetypes
import io
import zipfile

router = APIRouter()

# Pydantic models for file management
class FileListResponse(BaseModel):
    files: List[dict]
    total: int
    page: int
    limit: int
    total_pages: int
    storage_stats: dict

class FileDetailResponse(BaseModel):
    file: dict
    download_count: int
    last_download: Optional[datetime]
    file_integrity: dict

class FileSearchFilters(BaseModel):
    file_type: Optional[str] = None  # image, video, document, archive, other
    size_min: Optional[int] = None   # in bytes
    size_max: Optional[int] = None   # in bytes
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    owner_email: Optional[str] = None
    storage_location: Optional[str] = None
    status: Optional[str] = None

class BulkFileActionRequest(BaseModel):
    file_ids: List[str]
    action: str  # 'delete', 'move', 'quarantine', 'backup'
    reason: Optional[str] = None
    target_location: Optional[str] = None

@router.get("/files", response_model=FileListResponse)
async def list_files(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    size_min: Optional[int] = Query(None),
    size_max: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    owner_email: Optional[str] = Query(None),
    storage_location: Optional[str] = Query(None),
    file_status: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("upload_date"),
    sort_order: Optional[str] = Query("desc"),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """List all files with advanced filtering and search"""
    
    # Build query
    query = {}
    
    # Search filter - search in filename
    if search:
        query["filename"] = {"$regex": re.escape(search), "$options": "i"}
    
    # File type filter based on MIME type
    if file_type:
        type_patterns = {
            "image": "^image/",
            "video": "^video/", 
            "document": "^(application/(pdf|msword|vnd\\.openxmlformats-officedocument)|text/)",
            "archive": "^application/(zip|x-rar|x-7z|gzip|x-tar)",
            "audio": "^audio/"
        }
        if file_type in type_patterns:
            query["content_type"] = {"$regex": type_patterns[file_type]}
    
    # Size filters
    if size_min is not None or size_max is not None:
        size_query = {}
        if size_min is not None:
            size_query["$gte"] = size_min
        if size_max is not None:
            size_query["$lte"] = size_max
        query["size_bytes"] = size_query
    
    # Date filters
    if date_from or date_to:
        date_query = {}
        if date_from:
            try:
                date_query["$gte"] = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            except ValueError:
                pass
        if date_to:
            try:
                date_query["$lte"] = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            except ValueError:
                pass
        if date_query:
            query["upload_date"] = date_query
    
    # Owner filter
    if owner_email:
        # Get user by email
        user = db.users.find_one({"email": owner_email})
        if user:
            query["owner_id"] = user["_id"]
    
    # Storage location filter
    if storage_location and storage_location in ["gdrive", "hetzner"]:
        query["storage_location"] = storage_location
    
    # Status filter
    if file_status and file_status in ["pending", "uploading", "completed", "failed"]:
        query["status"] = file_status
    
    # Get total count (excluding deleted files)
    query["deleted_at"] = {"$exists": False}  # Exclude deleted files
    total = db.files.count_documents(query)
    
    # Calculate pagination
    skip = (page - 1) * limit
    total_pages = (total + limit - 1) // limit
    
    # Build sort
    sort_direction = 1 if sort_order == "asc" else -1
    sort_field = sort_by if sort_by in ["filename", "size_bytes", "upload_date", "status"] else "upload_date"
    
    # Get files
    files_cursor = db.files.find(query).sort(sort_field, sort_direction).skip(skip).limit(limit)
    files = list(files_cursor)
    
    # Enrich files with additional data
    for file_doc in files:
        # Get owner information
        if file_doc.get("owner_id"):
            owner = db.users.find_one({"_id": file_doc["owner_id"]}, {"email": 1, "_id": 0})
            file_doc["owner_email"] = owner["email"] if owner else "Unknown"
        else:
            file_doc["owner_email"] = "Anonymous"
        
        # Add file type based on MIME type
        content_type = file_doc.get("content_type", "")
        if content_type.startswith("image/"):
            file_doc["file_type"] = "image"
        elif content_type.startswith("video/"):
            file_doc["file_type"] = "video"
        elif content_type.startswith("audio/"):
            file_doc["file_type"] = "audio"
        elif any(x in content_type for x in ["pdf", "document", "text"]):
            file_doc["file_type"] = "document"
        elif any(x in content_type for x in ["zip", "rar", "7z", "tar", "gzip"]):
            file_doc["file_type"] = "archive"
        else:
            file_doc["file_type"] = "other"
        
        # Format size for display
        file_doc["size_formatted"] = format_file_size(file_doc.get("size_bytes", 0))
        
        # Add download URL
        file_doc["download_url"] = f"/api/v1/download/stream/{file_doc['_id']}"
    
    # Calculate storage statistics (excluding deleted files)
    total_storage = db.files.aggregate([
        {"$match": query},
        {"$group": {"_id": None, "total_size": {"$sum": "$size_bytes"}}}
    ])
    total_storage_result = list(total_storage)
    total_storage_bytes = total_storage_result[0]["total_size"] if total_storage_result else 0
    
    storage_stats = {
        "total_files": total,
        "total_storage": total_storage_bytes,
        "total_storage_formatted": format_file_size(total_storage_bytes),
        "average_file_size": total_storage_bytes // max(total, 1),
        "gdrive_files": db.files.count_documents({**query, "storage_location": "gdrive"}),
        "hetzner_files": db.files.count_documents({**query, "storage_location": "hetzner"})
    }
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="list_files",
        details=f"Listed files with filters: search='{search}', type='{file_type}', owner='{owner_email}'",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/files"
    )
    
    return FileListResponse(
        files=files,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        storage_stats=storage_stats
    )

@router.get("/files/{file_id}", response_model=FileDetailResponse)
async def get_file_detail(
    file_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get detailed file information"""
    
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    # Get owner information
    if file_doc.get("owner_id"):
        owner = db.users.find_one({"_id": file_doc["owner_id"]}, {"email": 1, "_id": 0})
        file_doc["owner_email"] = owner["email"] if owner else "Unknown"
    else:
        file_doc["owner_email"] = "Anonymous"
    
    # Add formatted size
    file_doc["size_formatted"] = format_file_size(file_doc.get("size_bytes", 0))
    
    # Mock download statistics (in production, track actual downloads)
    download_count = abs(hash(file_id)) % 100  # Mock download count
    last_download = file_doc.get("upload_date")  # Mock last download
    
    # File integrity check (mock implementation)
    file_integrity = {
        "status": "verified",
        "last_check": datetime.utcnow(),
        "checksum_match": True,
        "corruption_detected": False
    }
    
    # Add additional metadata
    file_doc["preview_available"] = is_previewable(file_doc.get("content_type", ""))
    file_doc["download_url"] = f"/api/v1/download/stream/{file_doc['_id']}"
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_file_detail",
        details=f"Viewed file details: {file_doc.get('filename', 'Unknown')} (ID: {file_id})",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/files/{file_id}"
    )
    
    return FileDetailResponse(
        file=file_doc,
        download_count=download_count,
        last_download=last_download,
        file_integrity=file_integrity
    )

@router.get("/files/{file_id}/preview")
async def get_file_preview(
    file_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get file preview (for images, videos, documents)"""
    
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    content_type = file_doc.get("content_type", "")
    
    # Check if file is previewable
    if not is_previewable(content_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File preview not supported for this file type"
        )
    
    # For now, return preview metadata
    # In production, this would return actual preview data or thumbnail
    preview_data = {
        "file_id": file_id,
        "filename": file_doc.get("filename"),
        "content_type": content_type,
        "preview_type": "thumbnail" if content_type.startswith("image/") else "viewer",
        "preview_url": f"/api/v1/download/stream/{file_id}",  # For now, link to actual file
        "can_stream": content_type.startswith(("video/", "audio/"))
    }
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="preview_file",
        details=f"Previewed file: {file_doc.get('filename', 'Unknown')} (ID: {file_id})",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/files/{file_id}/preview"
    )
    
    return preview_data

@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str,
    request: Request,
    reason: Optional[str] = Query(None),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Delete a file (admin only) - Deletes from Google Drive and marks as deleted in database"""
    
    print(f"🚀 [DELETE_FILE] ===== DELETION REQUEST RECEIVED =====")
    print(f"🚀 [DELETE_FILE] File ID: {file_id}")
    print(f"🚀 [DELETE_FILE] Admin: {current_admin.email}")
    print(f"🚀 [DELETE_FILE] Reason: {reason}")
    print(f"🚀 [DELETE_FILE] ============================================")
    
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    # Check if file is already deleted
    if file_doc.get("deleted_at") or file_doc.get("status") == "deleted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is already deleted"
        )
    
    deletion_errors = []
    filename = file_doc.get("filename", "Unknown")
    
    # 1. Delete from Google Drive if present
    gdrive_id = file_doc.get("gdrive_id")
    gdrive_account_id = file_doc.get("gdrive_account_id")
    
    print(f"[DELETE_FILE] File details - ID: {file_id}, GDrive ID: {gdrive_id}, Account: {gdrive_account_id}")
    
    if gdrive_id and gdrive_account_id:
        try:
            from app.services.google_drive_account_service import GoogleDriveAccountService
            from app.services.google_drive_service import delete_gdrive_file
            
            # Get the account configuration
            print(f"[DELETE_FILE] Looking up Google Drive account: {gdrive_account_id}")
            account = await GoogleDriveAccountService.get_account_by_id(gdrive_account_id)
            
            if account:
                print(f"[DELETE_FILE] Found account {account.account_id}, attempting to delete file {gdrive_id}")
                # Delete from Google Drive
                success = await delete_gdrive_file(gdrive_id, account.to_config())
                if success:
                    print(f"[DELETE_FILE] ✅ Successfully deleted {filename} from Google Drive account {gdrive_account_id}")
                    
                    # CRITICAL: Force account stats refresh from Google Drive API to reflect real deletion
                    try:
                        await GoogleDriveAccountService._update_account_quota(account)
                        print(f"[DELETE_FILE] ✅ Refreshed account stats from Google Drive API for {gdrive_account_id}")
                    except Exception as stats_error:
                        print(f"[DELETE_FILE] Warning: Failed to refresh account stats: {stats_error}")
                        
                else:
                    print(f"[DELETE_FILE] ⚠️  File {filename} not found in Google Drive (may have been manually deleted)")
            else:
                error_msg = f"Google Drive account {gdrive_account_id} not found in database"
                print(f"[DELETE_FILE] ❌ {error_msg}")
                deletion_errors.append(error_msg)
        except Exception as e:
            error_msg = f"Google Drive deletion failed: {str(e)}"
            print(f"[DELETE_FILE] ❌ Error deleting from Google Drive: {e}")
            deletion_errors.append(error_msg)
    else:
        if not gdrive_id:
            print(f"[DELETE_FILE] ⚠️  No gdrive_id found for file {file_id}, skipping Google Drive deletion")
        if not gdrive_account_id:
            print(f"[DELETE_FILE] ⚠️  No gdrive_account_id found for file {file_id}, skipping Google Drive deletion")
    
    # 2. Delete from Hetzner if present  
    hetzner_path = file_doc.get("hetzner_path")
    if hetzner_path:
        try:
            from app.services.hetzner_service import HetznerService
            hetzner_service = HetznerService()
            success = await hetzner_service.delete_file(hetzner_path)
            if success:
                print(f"[DELETE_FILE] Successfully deleted {filename} from Hetzner")
            else:
                deletion_errors.append("Hetzner deletion failed")
        except Exception as e:
            print(f"[DELETE_FILE] Error deleting from Hetzner: {e}")
            deletion_errors.append(f"Hetzner deletion failed: {str(e)}")
    
    # 3. Mark as deleted in database (always do this, even if storage deletion fails)
    update_doc = {
        "status": "deleted",
        "deleted_at": datetime.utcnow(),
        "deleted_by": current_admin.email,
        "deletion_reason": reason,
        "deletion_errors": deletion_errors if deletion_errors else None
    }
    
    db.files.update_one({"_id": file_id}, {"$set": update_doc})
    
    # 4. Note: Google Drive account stats are already refreshed above after successful deletion
    # This ensures stats always reflect the real state of Google Drive, not just MongoDB records
    
    # Log admin activity
    details = f"Deleted file: {filename} (ID: {file_id}). Reason: {reason or 'No reason provided'}"
    if deletion_errors:
        details += f". Errors: {'; '.join(deletion_errors)}"
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="delete_file",
        details=details,
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/files/{file_id}"
    )
    
    # Return response with any errors
    response = {"message": "File deleted successfully"}
    if deletion_errors:
        response["warnings"] = deletion_errors
        response["message"] = "File marked as deleted, but some storage operations failed"
    
    return response

@router.post("/files/test-gdrive-connection")
async def test_google_drive_connection(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Test Google Drive connection and list files"""
    try:
        from app.services.google_drive_account_service import GoogleDriveAccountService
        
        # Get all accounts
        accounts = await GoogleDriveAccountService.get_all_accounts()
        if not accounts:
            return {"error": "No Google Drive accounts found"}
        
        test_results = []
        for account in accounts:
            try:
                print(f"🧪 [TEST_GDRIVE] Testing account: {account.account_id}")
                
                # Try to refresh account quota (this tests API connectivity)
                await GoogleDriveAccountService._update_account_quota(account)
                
                test_results.append({
                    "account_id": account.account_id,
                    "email": account.email,
                    "status": "✅ Connected",
                    "files_count": account.files_count,
                    "storage_used": account.storage_used
                })
                
            except Exception as e:
                test_results.append({
                    "account_id": account.account_id,
                    "email": account.email, 
                    "status": f"❌ Error: {str(e)}",
                    "files_count": 0,
                    "storage_used": 0
                })
        
        return {"test_results": test_results}
        
    except Exception as e:
        return {"error": f"Test failed: {str(e)}"}

@router.post("/files/bulk-action")
async def bulk_file_action(
    action_data: BulkFileActionRequest,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Perform bulk actions on multiple files"""
    
    if len(action_data.file_ids) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot perform bulk action on more than 100 files at once"
        )
    
    # Verify all files exist
    existing_files = list(db.files.find({"_id": {"$in": action_data.file_ids}}, {"_id": 1, "filename": 1}))
    if len(existing_files) != len(action_data.file_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Some files not found"
        )
    
    update_doc = {"updated_at": datetime.utcnow()}
    action_msg = ""
    
    if action_data.action == "delete":
        update_doc.update({
            "status": "deleted",
            "deleted_at": datetime.utcnow(),
            "deleted_by": current_admin.email,
            "deletion_reason": action_data.reason
        })
        action_msg = "deleted"
    elif action_data.action == "quarantine":
        update_doc.update({
            "quarantined": True,
            "quarantined_at": datetime.utcnow(),
            "quarantined_by": current_admin.email,
            "quarantine_reason": action_data.reason
        })
        action_msg = "quarantined"
    elif action_data.action == "backup":
        update_doc.update({
            "backup_status": "in_progress",
            "backup_requested_at": datetime.utcnow(),
            "backup_requested_by": current_admin.email
        })
        action_msg = "marked for backup"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid action. Use 'delete', 'quarantine', or 'backup'"
        )
    
    # Perform bulk update
    result = db.files.update_many(
        {"_id": {"$in": action_data.file_ids}},
        {"$set": update_doc}
    )
    
    # Log admin activity
    filenames = [f["filename"] for f in existing_files[:5]]  # First 5 filenames
    filename_list = ", ".join(filenames)
    if len(existing_files) > 5:
        filename_list += f" (and {len(existing_files) - 5} more)"
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action=f"bulk_file_{action_data.action}",
        details=f"Bulk {action_msg} {result.modified_count} files: {filename_list}. Reason: {action_data.reason or 'No reason provided'}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/files/bulk-action"
    )
    
    return {
        "message": f"{result.modified_count} files {action_msg} successfully",
        "affected_count": result.modified_count
    }

@router.get("/files/analytics/types")
async def get_file_type_analytics(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get file type distribution analytics"""
    
    pipeline = [
        {
            "$match": {
                "deleted_at": {"$exists": False}  # Exclude deleted files
            }
        },
        {
            "$group": {
                "_id": {
                    "$cond": {
                        "if": {"$regexMatch": {"input": "$content_type", "regex": "^image/"}},
                        "then": "image",
                        "else": {
                            "$cond": {
                                "if": {"$regexMatch": {"input": "$content_type", "regex": "^video/"}},
                                "then": "video",
                                "else": {
                                    "$cond": {
                                        "if": {"$regexMatch": {"input": "$content_type", "regex": "^audio/"}},
                                        "then": "audio",
                                        "else": {
                                            "$cond": {
                                                "if": {"$regexMatch": {"input": "$content_type", "regex": "(pdf|document|text)"}},
                                                "then": "document",
                                                "else": {
                                                    "$cond": {
                                                        "if": {"$regexMatch": {"input": "$content_type", "regex": "(zip|rar|tar|gzip)"}},
                                                        "then": "archive",
                                                        "else": "other"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "count": {"$sum": 1},
                "total_size": {"$sum": "$size_bytes"}
            }
        },
        {"$sort": {"count": -1}}
    ]
    
    results = list(db.files.aggregate(pipeline))
    
    # Calculate percentages
    total_files = sum(result["count"] for result in results)
    for result in results:
        result["percentage"] = (result["count"] / max(total_files, 1)) * 100
        result["size_formatted"] = format_file_size(result["total_size"])
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_file_type_analytics",
        details="Viewed file type distribution analytics",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/files/analytics/types"
    )
    
    return {"file_types": results, "total_files": total_files}

@router.get("/files/analytics/storage-timeline")
async def get_storage_timeline(
    request: Request,
    days: int = Query(30, ge=7, le=365),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get storage usage over time"""
    
    from datetime import timedelta
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    pipeline = [
        {
            "$match": {
                "upload_date": {"$gte": start_date, "$lte": end_date}
            }
        },
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$upload_date"
                    }
                },
                "files_uploaded": {"$sum": 1},
                "storage_added": {"$sum": "$size_bytes"}
            }
        },
        {"$sort": {"_id": 1}}
    ]
    
    results = list(db.files.aggregate(pipeline))
    
    # Fill in missing dates with zero values
    timeline = []
    current_date = start_date
    results_dict = {r["_id"]: r for r in results}
    
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        if date_str in results_dict:
            timeline.append({
                "date": date_str,
                "files_uploaded": results_dict[date_str]["files_uploaded"],
                "storage_added": results_dict[date_str]["storage_added"],
                "storage_added_formatted": format_file_size(results_dict[date_str]["storage_added"])
            })
        else:
            timeline.append({
                "date": date_str,
                "files_uploaded": 0,
                "storage_added": 0,
                "storage_added_formatted": "0 B"
            })
        current_date += timedelta(days=1)
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_storage_timeline",
        details=f"Viewed storage timeline for {days} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/files/analytics/storage-timeline"
    )
    
    return {"timeline": timeline, "total_days": days}

# === FILE OPERATIONS ENDPOINTS ===

class FileOperationRequest(BaseModel):
    operation: str  # 'move', 'integrity_check', 'force_backup', 'recover'
    target_location: Optional[str] = None  # for move operations
    reason: Optional[str] = None

@router.post("/files/{file_id}/operation")
async def execute_file_operation(
    file_id: str,
    operation_data: FileOperationRequest,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Execute various file operations"""
    
    file_doc = db.files.find_one({"_id": file_id})
    if not file_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    if operation_data.operation == "move":
        return await move_file_between_accounts(file_id, file_doc, operation_data, current_admin, request)
    elif operation_data.operation == "integrity_check":
        return await check_file_integrity(file_id, file_doc, current_admin, request)
    elif operation_data.operation == "force_backup":
        return await force_file_backup(file_id, file_doc, operation_data, current_admin, request)
    elif operation_data.operation == "recover":
        return await recover_file_from_backup(file_id, file_doc, operation_data, current_admin, request)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid operation. Use 'move', 'integrity_check', 'force_backup', or 'recover'"
        )

async def move_file_between_accounts(file_id: str, file_doc: dict, operation_data: FileOperationRequest, current_admin: AdminUserInDB, request: Request):
    """Move file between Google Drive accounts"""
    
    if not operation_data.target_location:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target location required for move operation"
        )
    
    # TODO: Implement actual file movement between Google Drive accounts
    # For now, simulate the operation
    
    update_doc = {
        "gdrive_account_id": operation_data.target_location,
        "moved_at": datetime.utcnow(),
        "moved_by": current_admin.email,
        "move_reason": operation_data.reason
    }
    
    db.files.update_one({"_id": file_id}, {"$set": update_doc})
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="move_file",
        details=f"Moved file {file_doc.get('filename', 'Unknown')} to {operation_data.target_location}. Reason: {operation_data.reason or 'No reason provided'}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/files/{file_id}/operation"
    )
    
    return {"message": "File moved successfully", "target_location": operation_data.target_location}

async def check_file_integrity(file_id: str, file_doc: dict, current_admin: AdminUserInDB, request: Request):
    """Check file integrity and corruption"""
    
    # TODO: Implement actual integrity checking
    # For now, simulate the check
    
    import hashlib
    integrity_result = {
        "status": "verified",
        "checksum_match": True,
        "corruption_detected": False,
        "file_accessible": True,
        "last_check": datetime.utcnow(),
        "check_performed_by": current_admin.email
    }
    
    # Simulate random integrity issues for testing
    file_hash = abs(hash(file_id)) % 100
    if file_hash < 5:  # 5% chance of simulated corruption
        integrity_result.update({
            "status": "corrupted",
            "checksum_match": False,
            "corruption_detected": True,
            "corruption_type": "checksum_mismatch"
        })
    elif file_hash < 10:  # Additional 5% chance of inaccessible file
        integrity_result.update({
            "status": "inaccessible",
            "file_accessible": False,
            "error": "File not found in storage location"
        })
    
    # Update file record with integrity check results
    db.files.update_one(
        {"_id": file_id},
        {
            "$set": {
                "last_integrity_check": datetime.utcnow(),
                "integrity_status": integrity_result["status"]
            }
        }
    )
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="check_file_integrity",
        details=f"Integrity check for {file_doc.get('filename', 'Unknown')}: {integrity_result['status']}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/files/{file_id}/operation"
    )
    
    return {"integrity_check": integrity_result}

async def force_file_backup(file_id: str, file_doc: dict, operation_data: FileOperationRequest, current_admin: AdminUserInDB, request: Request):
    """Force backup of file to Hetzner"""
    
    # Check if file is already backed up
    if file_doc.get("backup_status") == "completed":
        return {"message": "File is already backed up", "backup_status": "completed"}
    
    # Use the actual backup service
    from app.services import backup_service
    import asyncio
    
    # Update file to mark backup in progress with admin tracking
    db.files.update_one(
        {"_id": file_id},
        {
            "$set": {
                "backup_status": "in_progress",
                "backup_started_at": datetime.utcnow(),
                "backup_requested_by": current_admin.email,
                "backup_reason": operation_data.reason
            }
        }
    )
    
    # Start the actual backup process as a background task
    backup_path = f"{file_id}/{file_doc.get('filename', 'unknown')}"
    
    try:
        # Run backup in background task
        asyncio.create_task(backup_service.transfer_gdrive_to_hetzner(file_id))
        
        # Log admin activity
        await log_admin_activity(
            admin_email=current_admin.email,
            action="force_backup",
            details=f"Initiated backup for {file_doc.get('filename', 'Unknown')}. Reason: {operation_data.reason or 'Manual backup request'}",
            ip_address=get_client_ip(request),
            endpoint=f"/api/v1/admin/files/{file_id}/operation"
        )
        
        return {"message": "File backup initiated", "backup_path": backup_path, "status": "in_progress"}
        
    except Exception as e:
        # Update backup status to failed
        db.files.update_one(
            {"_id": file_id},
            {
                "$set": {
                    "backup_status": "failed",
                    "backup_error": str(e),
                    "backup_failed_at": datetime.utcnow()
                }
            }
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate backup: {str(e)}"
        )

async def recover_file_from_backup(file_id: str, file_doc: dict, operation_data: FileOperationRequest, current_admin: AdminUserInDB, request: Request):
    """Recover file from backup"""
    
    if file_doc.get("backup_status") != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File has no completed backup to recover from"
        )
    
    # Check if file has Hetzner backup path
    hetzner_path = file_doc.get("hetzner_remote_path")
    if not hetzner_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File backup path not found"
        )
    
    # Update file status to indicate recovery in progress
    db.files.update_one(
        {"_id": file_id},
        {
            "$set": {
                "recovery_status": "in_progress",
                "recovery_started_at": datetime.utcnow(),
                "recovery_requested_by": current_admin.email,
                "recovery_reason": operation_data.reason
            }
        }
    )
    
    try:
        # Verify file exists in Hetzner backup
        from app.core.config import settings
        import httpx
        
        auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
        backup_url = f"{settings.HETZNER_WEBDAV_URL}/{hetzner_path}"
        
        async with httpx.AsyncClient(auth=auth) as client:
            # Check if backup file exists
            head_response = await client.head(backup_url)
            if head_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Backup file not found in Hetzner storage"
                )
        
        # Mark recovery as completed
        db.files.update_one(
            {"_id": file_id},
            {
                "$set": {
                    "recovery_status": "completed",
                    "recovery_completed_at": datetime.utcnow(),
                    "status": "completed",  # Restore file to completed status
                    "recovered_from": "hetzner_backup",
                    "recovery_verified_at": datetime.utcnow()
                }
            }
        )
        
        # Log admin activity
        await log_admin_activity(
            admin_email=current_admin.email,
            action="recover_file",
            details=f"Verified recovery of file {file_doc.get('filename', 'Unknown')} from backup. Reason: {operation_data.reason or 'File recovery request'}",
            ip_address=get_client_ip(request),
            endpoint=f"/api/v1/admin/files/{file_id}/operation"
        )
        
        return {"message": "File recovery verified successfully", "backup_url": backup_url}
        
    except HTTPException:
        raise
    except Exception as e:
        # Mark recovery as failed
        db.files.update_one(
            {"_id": file_id},
            {
                "$set": {
                    "recovery_status": "failed",
                    "recovery_error": str(e),
                    "recovery_failed_at": datetime.utcnow()
                }
            }
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File recovery failed: {str(e)}"
        )

@router.get("/files/orphaned")
async def get_orphaned_files(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get orphaned files (files without valid storage references)"""
    
    # Find files that might be orphaned
    query = {
        "$or": [
            {"gdrive_id": {"$exists": False}},
            {"gdrive_id": None},
            {"status": "failed"},
            {"storage_location": None}
        ]
    }
    
    total = db.files.count_documents(query)
    skip = (page - 1) * limit
    total_pages = (total + limit - 1) // limit
    
    orphaned_files = list(
        db.files.find(query)
        .sort("upload_date", -1)
        .skip(skip)
        .limit(limit)
    )
    
    # Enrich with additional metadata
    for file_doc in orphaned_files:
        file_doc["size_formatted"] = format_file_size(file_doc.get("size_bytes", 0))
        file_doc["orphan_reason"] = determine_orphan_reason(file_doc)
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_orphaned_files",
        details=f"Viewed orphaned files list (page {page})",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/files/orphaned"
    )
    
    return {
        "orphaned_files": orphaned_files,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages
    }

@router.post("/files/cleanup-orphaned")
async def cleanup_orphaned_files(
    request: Request,
    cleanup_type: str = Query("soft", pattern="^(soft|hard)$"),
    days_old: int = Query(7, ge=1, le=365),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Cleanup orphaned files"""
    
    from datetime import timedelta
    
    cutoff_date = datetime.utcnow() - timedelta(days=days_old)
    
    # Find orphaned files older than specified days
    query = {
        "$or": [
            {"gdrive_id": {"$exists": False}},
            {"gdrive_id": None},
            {"status": "failed"}
        ],
        "upload_date": {"$lte": cutoff_date}
    }
    
    orphaned_files = list(db.files.find(query, {"_id": 1, "filename": 1}))
    
    if cleanup_type == "soft":
        # Mark as deleted but keep records
        result = db.files.update_many(
            query,
            {
                "$set": {
                    "deleted": True,
                    "deleted_at": datetime.utcnow(),
                    "deleted_by": current_admin.email,
                    "deletion_reason": f"Orphaned file cleanup (older than {days_old} days)"
                }
            }
        )
        action = "soft deleted (marked as deleted)"
    else:
        # Hard delete - remove from database
        result = db.files.delete_many(query)
        action = "hard deleted (removed from database)"
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="cleanup_orphaned_files",
        details=f"Cleanup orphaned files: {action} {result.modified_count if cleanup_type == 'soft' else result.deleted_count} files older than {days_old} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/files/cleanup-orphaned"
    )
    
    return {
        "message": f"Orphaned files cleanup completed ({action})",
        "files_affected": result.modified_count if cleanup_type == "soft" else result.deleted_count,
        "cleanup_type": cleanup_type,
        "days_old": days_old
    }

def determine_orphan_reason(file_doc: dict) -> str:
    """Determine why a file is considered orphaned"""
    
    if not file_doc.get("gdrive_id"):
        return "Missing Google Drive ID"
    elif file_doc.get("status") == "failed":
        return "Upload failed"
    elif not file_doc.get("storage_location"):
        return "No storage location specified"
    else:
        return "Unknown orphan reason"

# === FILE ANALYTICS ENDPOINTS ===

@router.get("/files/analytics/upload-download-stats")
async def get_upload_download_stats(
    request: Request,
    days: int = Query(30, ge=7, le=365),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get upload and download statistics"""
    
    from datetime import timedelta
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    # Upload statistics
    upload_pipeline = [
        {
            "$match": {
                "upload_date": {"$gte": start_date, "$lte": end_date}
            }
        },
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$upload_date"
                    }
                },
                "uploads": {"$sum": 1},
                "upload_volume": {"$sum": "$size_bytes"},
                "successful_uploads": {
                    "$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}
                },
                "failed_uploads": {
                    "$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}
                }
            }
        },
        {"$sort": {"_id": 1}}
    ]
    
    upload_results = list(db.files.aggregate(upload_pipeline))
    
    # Mock download statistics (in production, you'd track actual downloads)
    download_stats = []
    for result in upload_results:
        # Simulate downloads as a percentage of successful uploads
        successful_uploads = result["successful_uploads"]
        mock_downloads = int(successful_uploads * 1.5)  # Assume 1.5x download rate
        download_stats.append({
            "date": result["_id"],
            "downloads": mock_downloads,
            "download_volume": int(result["upload_volume"] * 1.2)  # Mock download volume
        })
    
    # Overall statistics
    total_files = db.files.count_documents({"upload_date": {"$gte": start_date, "$lte": end_date}})
    successful_uploads = db.files.count_documents({
        "upload_date": {"$gte": start_date, "$lte": end_date},
        "status": "completed"
    })
    failed_uploads = db.files.count_documents({
        "upload_date": {"$gte": start_date, "$lte": end_date},
        "status": "failed"
    })
    
    success_rate = (successful_uploads / max(total_files, 1)) * 100
    failure_rate = (failed_uploads / max(total_files, 1)) * 100
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_upload_download_stats",
        details=f"Viewed upload/download statistics for {days} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/files/analytics/upload-download-stats"
    )
    
    return {
        "upload_stats": upload_results,
        "download_stats": download_stats,
        "summary": {
            "total_files": total_files,
            "successful_uploads": successful_uploads,
            "failed_uploads": failed_uploads,
            "success_rate": round(success_rate, 2),
            "failure_rate": round(failure_rate, 2),
            "period_days": days
        }
    }

@router.get("/files/analytics/popular-files")
async def get_popular_files(
    request: Request,
    limit: int = Query(20, ge=5, le=100),
    period_days: int = Query(30, ge=7, le=365),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get most popular files by download count"""
    
    from datetime import timedelta
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=period_days)
    
    # Get files from the specified period
    files = list(db.files.find(
        {
            "upload_date": {"$gte": start_date, "$lte": end_date},
            "status": "completed"
        },
        {
            "_id": 1,
            "filename": 1,
            "size_bytes": 1,
            "content_type": 1,
            "upload_date": 1,
            "owner_id": 1
        }
    ).limit(limit * 2))  # Get more files to simulate popularity
    
    # Mock popularity ranking based on file characteristics
    popular_files = []
    for file_doc in files:
        # Simulate download count based on file characteristics
        base_downloads = abs(hash(file_doc["_id"])) % 1000
        
        # Boost popularity for certain file types
        content_type = file_doc.get("content_type", "")
        if "image" in content_type:
            popularity_multiplier = 1.5
        elif "video" in content_type:
            popularity_multiplier = 2.0
        elif "pdf" in content_type:
            popularity_multiplier = 1.8
        else:
            popularity_multiplier = 1.0
        
        download_count = int(base_downloads * popularity_multiplier)
        
        # Get owner information
        owner_email = "Anonymous"
        if file_doc.get("owner_id"):
            owner = db.users.find_one({"_id": file_doc["owner_id"]}, {"email": 1})
            if owner:
                owner_email = owner["email"]
        
        popular_files.append({
            "_id": file_doc["_id"],
            "filename": file_doc["filename"],
            "size_formatted": format_file_size(file_doc["size_bytes"]),
            "content_type": file_doc["content_type"],
            "upload_date": file_doc["upload_date"],
            "owner_email": owner_email,
            "download_count": download_count,
            "popularity_score": download_count * popularity_multiplier
        })
    
    # Sort by popularity and limit results
    popular_files.sort(key=lambda x: x["popularity_score"], reverse=True)
    popular_files = popular_files[:limit]
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_popular_files",
        details=f"Viewed top {limit} popular files for {period_days} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/files/analytics/popular-files"
    )
    
    return {
        "popular_files": popular_files,
        "total_analyzed": len(files),
        "period_days": period_days,
        "limit": limit
    }

@router.get("/files/analytics/size-distribution")
async def get_file_size_distribution(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get file size distribution analytics"""
    
    # Define size ranges
    size_ranges = [
        {"label": "< 1 MB", "min": 0, "max": 1024 * 1024},
        {"label": "1-10 MB", "min": 1024 * 1024, "max": 10 * 1024 * 1024},
        {"label": "10-100 MB", "min": 10 * 1024 * 1024, "max": 100 * 1024 * 1024},
        {"label": "100MB-1GB", "min": 100 * 1024 * 1024, "max": 1024 * 1024 * 1024},
        {"label": "1-5 GB", "min": 1024 * 1024 * 1024, "max": 5 * 1024 * 1024 * 1024},
        {"label": "> 5 GB", "min": 5 * 1024 * 1024 * 1024, "max": float('inf')}
    ]
    
    distribution = []
    total_files = 0
    
    for size_range in size_ranges:
        query = {"size_bytes": {"$gte": size_range["min"]}}
        if size_range["max"] != float('inf'):
            query["size_bytes"]["$lt"] = size_range["max"]
        
        count = db.files.count_documents(query)
        total_files += count
        
        # Calculate total storage for this range
        pipeline = [
            {"$match": query},
            {"$group": {"_id": None, "total_size": {"$sum": "$size_bytes"}}}
        ]
        size_result = list(db.files.aggregate(pipeline))
        total_size = size_result[0]["total_size"] if size_result else 0
        
        distribution.append({
            "range": size_range["label"],
            "count": count,
            "total_size": total_size,
            "total_size_formatted": format_file_size(total_size),
            "percentage": 0  # Will be calculated after we have total_files
        })
    
    # Calculate percentages
    for item in distribution:
        item["percentage"] = (item["count"] / max(total_files, 1)) * 100
    
    # Get additional statistics
    pipeline = [
        {
            "$group": {
                "_id": None,
                "avg_size": {"$avg": "$size_bytes"},
                "max_size": {"$max": "$size_bytes"},
                "min_size": {"$min": "$size_bytes"},
                "total_size": {"$sum": "$size_bytes"}
            }
        }
    ]
    
    stats_result = list(db.files.aggregate(pipeline))
    stats = stats_result[0] if stats_result else {
        "avg_size": 0, "max_size": 0, "min_size": 0, "total_size": 0
    }
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_size_distribution",
        details="Viewed file size distribution analytics",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/files/analytics/size-distribution"
    )
    
    return {
        "distribution": distribution,
        "statistics": {
            "total_files": total_files,
            "average_size": stats["avg_size"],
            "average_size_formatted": format_file_size(stats["avg_size"]),
            "largest_file": stats["max_size"],
            "largest_file_formatted": format_file_size(stats["max_size"]),
            "smallest_file": stats["min_size"],
            "smallest_file_formatted": format_file_size(stats["min_size"]),
            "total_storage": stats["total_size"],
            "total_storage_formatted": format_file_size(stats["total_size"])
        }
    }

@router.get("/files/analytics/failed-uploads")
async def get_failed_upload_analysis(
    request: Request,
    days: int = Query(30, ge=7, le=365),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get failed upload analysis"""
    
    from datetime import timedelta
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    # Get failed uploads
    failed_uploads = list(db.files.find(
        {
            "upload_date": {"$gte": start_date, "$lte": end_date},
            "status": "failed"
        },
        {
            "_id": 1,
            "filename": 1,
            "size_bytes": 1,
            "content_type": 1,
            "upload_date": 1,
            "owner_id": 1,
            "gdrive_account_id": 1
        }
    ))
    
    # Analyze failure patterns
    failure_by_type = {}
    failure_by_size = {"< 10MB": 0, "10-100MB": 0, "100MB-1GB": 0, "> 1GB": 0}
    failure_by_account = {}
    failure_timeline = {}
    
    for file_doc in failed_uploads:
        # Group by content type
        content_type = file_doc.get("content_type", "unknown")
        main_type = content_type.split("/")[0] if "/" in content_type else content_type
        failure_by_type[main_type] = failure_by_type.get(main_type, 0) + 1
        
        # Group by file size
        size_bytes = file_doc.get("size_bytes", 0)
        if size_bytes < 10 * 1024 * 1024:
            failure_by_size["< 10MB"] += 1
        elif size_bytes < 100 * 1024 * 1024:
            failure_by_size["10-100MB"] += 1
        elif size_bytes < 1024 * 1024 * 1024:
            failure_by_size["100MB-1GB"] += 1
        else:
            failure_by_size["> 1GB"] += 1
        
        # Group by account
        account_id = file_doc.get("gdrive_account_id", "unknown")
        failure_by_account[account_id] = failure_by_account.get(account_id, 0) + 1
        
        # Group by date
        date_str = file_doc["upload_date"].strftime("%Y-%m-%d")
        failure_timeline[date_str] = failure_timeline.get(date_str, 0) + 1
    
    # Convert to lists for easier frontend consumption
    failure_by_type_list = [{"type": k, "count": v} for k, v in failure_by_type.items()]
    failure_by_size_list = [{"size_range": k, "count": v} for k, v in failure_by_size.items()]
    failure_by_account_list = [{"account": k, "count": v} for k, v in failure_by_account.items()]
    failure_timeline_list = [{"date": k, "count": v} for k, v in sorted(failure_timeline.items())]
    
    # Get total statistics
    total_uploads = db.files.count_documents({"upload_date": {"$gte": start_date, "$lte": end_date}})
    failure_rate = (len(failed_uploads) / max(total_uploads, 1)) * 100
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_failed_uploads",
        details=f"Viewed failed upload analysis for {days} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/files/analytics/failed-uploads"
    )
    
    return {
        "failed_uploads": len(failed_uploads),
        "total_uploads": total_uploads,
        "failure_rate": round(failure_rate, 2),
        "period_days": days,
        "failure_patterns": {
            "by_type": failure_by_type_list,
            "by_size": failure_by_size_list,
            "by_account": failure_by_account_list,
            "timeline": failure_timeline_list
        },
        "recommendations": generate_failure_recommendations(failure_by_type, failure_by_size, failure_by_account)
    }

def generate_failure_recommendations(failure_by_type: dict, failure_by_size: dict, failure_by_account: dict) -> list:
    """Generate recommendations based on failure patterns"""
    
    recommendations = []
    
    # Check for high failure rates in specific file types
    total_failures = sum(failure_by_type.values())
    if total_failures > 0:
        for file_type, count in failure_by_type.items():
            percentage = (count / total_failures) * 100
            if percentage > 30:
                recommendations.append(f"High failure rate for {file_type} files ({percentage:.1f}%). Consider reviewing upload process for this file type.")
    
    # Check for large file failures
    large_file_failures = failure_by_size.get("> 1GB", 0) + failure_by_size.get("100MB-1GB", 0)
    if large_file_failures > total_failures * 0.3:
        recommendations.append("High failure rate for large files. Consider implementing chunked upload or increasing timeout limits.")
    
    # Check for account-specific issues
    if len(failure_by_account) > 0:
        max_account_failures = max(failure_by_account.values())
        if max_account_failures > total_failures * 0.4:
            problem_account = max(failure_by_account.keys(), key=lambda k: failure_by_account[k])
            recommendations.append(f"Account {problem_account} has unusually high failure rate. Check account quotas and permissions.")
    
    if not recommendations:
        recommendations.append("No significant failure patterns detected. System appears to be operating normally.")
    
    return recommendations

# Helper functions
def format_file_size(bytes_size: int) -> str:
    """Format file size in human readable format"""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024):.1f} GB"

def is_previewable(content_type: str) -> bool:
    """Check if file type supports preview"""
    previewable_types = [
        "image/", "video/", "audio/", "text/", "application/pdf"
    ]
    return any(content_type.startswith(ptype) for ptype in previewable_types)

# ================================
# DRIVE FILE MANAGEMENT ENDPOINTS
# ================================

@router.get("/drive/files")
async def list_drive_files(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    size_min: Optional[int] = Query(None),
    size_max: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    owner_email: Optional[str] = Query(None),
    backup_status: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("upload_date"),
    sort_order: Optional[str] = Query("desc"),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """List files that are stored on Google Drive (primary storage)"""
    
    # Build query for files stored on Google Drive
    query = {
        "storage_location": StorageLocation.GDRIVE,
        "status": UploadStatus.COMPLETED,
        "deleted_at": {"$exists": False}  # Exclude deleted files
    }
    
    # Search filter - search in filename
    if search:
        query["filename"] = {"$regex": re.escape(search), "$options": "i"}
    
    # File type filter based on MIME type
    if file_type:
        type_patterns = {
            "image": "^image/",
            "video": "^video/", 
            "document": "^(application/(pdf|msword|vnd\\.openxmlformats-officedocument)|text/)",
            "archive": "^application/(zip|x-rar|x-7z|gzip|x-tar)",
            "audio": "^audio/"
        }
        if file_type in type_patterns:
            query["content_type"] = {"$regex": type_patterns[file_type]}
    
    # Size filters
    if size_min is not None or size_max is not None:
        size_query = {}
        if size_min is not None:
            size_query["$gte"] = size_min
        if size_max is not None:
            size_query["$lte"] = size_max
        query["size_bytes"] = size_query
    
    # Date filters
    if date_from or date_to:
        date_query = {}
        if date_from:
            try:
                date_from_obj = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                date_query["$gte"] = date_from_obj
            except ValueError:
                pass
        if date_to:
            try:
                date_to_obj = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                date_query["$lte"] = date_to_obj
            except ValueError:
                pass
        if date_query:
            query["upload_date"] = date_query
    
    # Owner filter
    if owner_email:
        query["owner_email"] = {"$regex": re.escape(owner_email), "$options": "i"}
    
    # Backup status filter
    if backup_status:
        query["backup_status"] = backup_status
    
    # Build sort
    sort_field = sort_by if sort_by in ["filename", "size_bytes", "upload_date", "backup_status"] else "upload_date"
    sort_direction = 1 if sort_order == "asc" else -1
    sort = [(sort_field, sort_direction)]
    
    # Get total count
    total_files = db.files.count_documents(query)
    
    # Calculate pagination
    skip = (page - 1) * limit
    total_pages = (total_files + limit - 1) // limit
    
    # Get files
    files_cursor = db.files.find(query).sort(sort).skip(skip).limit(limit)
    files = []
    
    for file_doc in files_cursor:
        file_doc["_id"] = str(file_doc["_id"])
        file_doc["size_formatted"] = format_file_size(file_doc.get("size_bytes", 0))
        files.append(file_doc)
    
    # Get drive-specific statistics (excluding deleted files)
    drive_stats = {
        "total_files": db.files.count_documents({
            "storage_location": StorageLocation.GDRIVE, 
            "status": UploadStatus.COMPLETED,
            "deleted_at": {"$exists": False}  # Exclude deleted files
        }),
        "total_storage": 0,
        "total_storage_formatted": "0 B",
        "transferring_to_hetzner": db.files.count_documents({
            "storage_location": StorageLocation.GDRIVE, 
            "backup_status": BackupStatus.IN_PROGRESS,
            "deleted_at": {"$exists": False}  # Exclude deleted files
        }),
        "backed_up_to_hetzner": db.files.count_documents({
            "storage_location": StorageLocation.GDRIVE, 
            "backup_status": BackupStatus.COMPLETED,
            "deleted_at": {"$exists": False}  # Exclude deleted files
        }),
        "failed_backups": db.files.count_documents({
            "storage_location": StorageLocation.GDRIVE, 
            "backup_status": BackupStatus.FAILED,
            "deleted_at": {"$exists": False}  # Exclude deleted files
        })
    }
    
    # Calculate total storage (excluding deleted files)
    storage_pipeline = [
        {
            "$match": {
                "storage_location": StorageLocation.GDRIVE, 
                "status": UploadStatus.COMPLETED,
                "deleted_at": {"$exists": False}  # Exclude deleted files
            }
        },
        {"$group": {"_id": None, "total_size": {"$sum": "$size_bytes"}}}
    ]
    storage_result = list(db.files.aggregate(storage_pipeline))
    if storage_result:
        drive_stats["total_storage"] = storage_result[0]["total_size"]
        drive_stats["total_storage_formatted"] = format_file_size(storage_result[0]["total_size"])
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="list_drive_files",
        details=f"Listed {len(files)} drive files (page {page})",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/drive/files"
    )
    
    return {
        "files": files,
        "total": total_files,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "drive_stats": drive_stats
    }

@router.get("/drive/analytics")
async def get_drive_analytics(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get analytics for Google Drive files"""
    
    # File type distribution (excluding deleted files)
    type_pipeline = [
        {
            "$match": {
                "storage_location": StorageLocation.GDRIVE, 
                "status": UploadStatus.COMPLETED,
                "deleted_at": {"$exists": False}  # Exclude deleted files
            }
        },
        {"$group": {
            "_id": "$file_type",
            "count": {"$sum": 1},
            "total_size": {"$sum": "$size_bytes"}
        }},
        {"$sort": {"count": -1}}
    ]
    
    type_results = list(db.files.aggregate(type_pipeline))
    total_files = sum(item["count"] for item in type_results)
    
    file_types = []
    for item in type_results:
        percentage = (item["count"] / total_files * 100) if total_files > 0 else 0
        file_types.append({
            "_id": item["_id"] or "unknown",
            "count": item["count"],
            "total_size": item["total_size"],
            "size_formatted": format_file_size(item["total_size"]),
            "percentage": percentage
        })
    
    # Backup status distribution (excluding deleted files)
    backup_pipeline = [
        {
            "$match": {
                "storage_location": StorageLocation.GDRIVE, 
                "status": UploadStatus.COMPLETED,
                "deleted_at": {"$exists": False}  # Exclude deleted files
            }
        },
        {"$group": {
            "_id": "$backup_status",
            "count": {"$sum": 1}
        }}
    ]
    
    backup_results = list(db.files.aggregate(backup_pipeline))
    backup_distribution = {}
    for item in backup_results:
        backup_distribution[item["_id"]] = item["count"]
    
    # Account distribution (excluding deleted files)
    account_pipeline = [
        {
            "$match": {
                "storage_location": StorageLocation.GDRIVE, 
                "status": UploadStatus.COMPLETED,
                "deleted_at": {"$exists": False}  # Exclude deleted files
            }
        },
        {"$group": {
            "_id": "$gdrive_account_id",
            "count": {"$sum": 1},
            "total_size": {"$sum": "$size_bytes"}
        }},
        {"$sort": {"count": -1}}
    ]
    
    account_results = list(db.files.aggregate(account_pipeline))
    account_distribution = []
    for item in account_results:
        account_distribution.append({
            "account_id": item["_id"],
            "count": item["count"],
            "total_size": item["total_size"],
            "size_formatted": format_file_size(item["total_size"])
        })
    
    return {
        "file_types": file_types,
        "total_files": total_files,
        "backup_distribution": backup_distribution,
        "account_distribution": account_distribution
    }

# ================================
# HETZNER FILE MANAGEMENT ENDPOINTS
# ================================

@router.get("/hetzner/files")
async def list_hetzner_files(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    size_min: Optional[int] = Query(None),
    size_max: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    owner_email: Optional[str] = Query(None),
    backup_status: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("upload_date"),
    sort_order: Optional[str] = Query("desc"),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """List files that are backed up to Hetzner storage"""
    
    # Build query for files backed up to Hetzner (excluding deleted files)
    query = {
        "backup_status": BackupStatus.COMPLETED,
        "backup_location": StorageLocation.HETZNER,
        "deleted_at": {"$exists": False}  # Exclude deleted files
    }
    
    # Search filter - search in filename
    if search:
        query["filename"] = {"$regex": re.escape(search), "$options": "i"}
    
    # File type filter based on MIME type
    if file_type:
        type_patterns = {
            "image": "^image/",
            "video": "^video/", 
            "document": "^(application/(pdf|msword|vnd\\.openxmlformats-officedocument)|text/)",
            "archive": "^application/(zip|x-rar|x-7z|gzip|x-tar)",
            "audio": "^audio/"
        }
        if file_type in type_patterns:
            query["content_type"] = {"$regex": type_patterns[file_type]}
    
    # Size filters
    if size_min is not None or size_max is not None:
        size_query = {}
        if size_min is not None:
            size_query["$gte"] = size_min
        if size_max is not None:
            size_query["$lte"] = size_max
        query["size_bytes"] = size_query
    
    # Date filters
    if date_from or date_to:
        date_query = {}
        if date_from:
            try:
                date_from_obj = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                date_query["$gte"] = date_from_obj
            except ValueError:
                pass
        if date_to:
            try:
                date_to_obj = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                date_query["$lte"] = date_to_obj
            except ValueError:
                pass
        if date_query:
            query["upload_date"] = date_query
    
    # Owner filter
    if owner_email:
        query["owner_email"] = {"$regex": re.escape(owner_email), "$options": "i"}
    
    # Build sort
    sort_field = sort_by if sort_by in ["filename", "size_bytes", "upload_date", "backup_status"] else "upload_date"
    sort_direction = 1 if sort_order == "asc" else -1
    sort = [(sort_field, sort_direction)]
    
    # Get total count
    total_files = db.files.count_documents(query)
    
    # Calculate pagination
    skip = (page - 1) * limit
    total_pages = (total_files + limit - 1) // limit
    
    # Get files
    files_cursor = db.files.find(query).sort(sort).skip(skip).limit(limit)
    files = []
    
    for file_doc in files_cursor:
        file_doc["_id"] = str(file_doc["_id"])
        file_doc["size_formatted"] = format_file_size(file_doc.get("size_bytes", 0))
        files.append(file_doc)
    
    # Get hetzner-specific statistics (excluding deleted files)
    hetzner_stats = {
        "total_files": db.files.count_documents({
            "backup_status": BackupStatus.COMPLETED, 
            "backup_location": StorageLocation.HETZNER,
            "deleted_at": {"$exists": False}  # Exclude deleted files
        }),
        "total_storage": 0,
        "total_storage_formatted": "0 B",
        "recent_backups": db.files.count_documents({
            "backup_status": BackupStatus.COMPLETED, 
            "backup_location": StorageLocation.HETZNER,
            "deleted_at": {"$exists": False},  # Exclude deleted files
            "upload_date": {"$gte": datetime.utcnow() - timedelta(days=7)}
        }),
        "failed_backups": db.files.count_documents({
            "backup_status": BackupStatus.FAILED,
            "deleted_at": {"$exists": False}  # Exclude deleted files
        })
    }
    
    # Calculate total storage (excluding deleted files)
    storage_pipeline = [
        {
            "$match": {
                "backup_status": BackupStatus.COMPLETED, 
                "backup_location": StorageLocation.HETZNER,
                "deleted_at": {"$exists": False}  # Exclude deleted files
            }
        },
        {"$group": {"_id": None, "total_size": {"$sum": "$size_bytes"}}}
    ]
    storage_result = list(db.files.aggregate(storage_pipeline))
    if storage_result:
        hetzner_stats["total_storage"] = storage_result[0]["total_size"]
        hetzner_stats["total_storage_formatted"] = format_file_size(storage_result[0]["total_size"])
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="list_hetzner_files",
        details=f"Listed {len(files)} hetzner files (page {page})",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/hetzner/files"
    )
    
    return {
        "files": files,
        "total": total_files,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "hetzner_stats": hetzner_stats
    }

@router.get("/hetzner/analytics")
async def get_hetzner_analytics(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get analytics for Hetzner backup files"""
    
    # File type distribution (excluding deleted files)
    type_pipeline = [
        {
            "$match": {
                "backup_status": BackupStatus.COMPLETED, 
                "backup_location": StorageLocation.HETZNER,
                "deleted_at": {"$exists": False}  # Exclude deleted files
            }
        },
        {"$group": {
            "_id": "$file_type",
            "count": {"$sum": 1},
            "total_size": {"$sum": "$size_bytes"}
        }},
        {"$sort": {"count": -1}}
    ]
    
    type_results = list(db.files.aggregate(type_pipeline))
    total_files = sum(item["count"] for item in type_results)
    
    file_types = []
    for item in type_results:
        percentage = (item["count"] / total_files * 100) if total_files > 0 else 0
        file_types.append({
            "_id": item["_id"] or "unknown",
            "count": item["count"],
            "total_size": item["total_size"],
            "size_formatted": format_file_size(item["total_size"]),
            "percentage": percentage
        })
    
    # Backup timeline (last 30 days) - excluding deleted files
    timeline_pipeline = [
        {
            "$match": {
                "backup_status": BackupStatus.COMPLETED, 
                "backup_location": StorageLocation.HETZNER,
                "deleted_at": {"$exists": False},  # Exclude deleted files
                "upload_date": {"$gte": datetime.utcnow() - timedelta(days=30)}
            }
        },
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$upload_date"}},
            "count": {"$sum": 1},
            "total_size": {"$sum": "$size_bytes"}
        }},
        {"$sort": {"_id": 1}}
    ]
    
    timeline_results = list(db.files.aggregate(timeline_pipeline))
    backup_timeline = []
    for item in timeline_results:
        backup_timeline.append({
            "date": item["_id"],
            "count": item["count"],
            "total_size": item["total_size"],
            "size_formatted": format_file_size(item["total_size"])
        })
    
    # Source account distribution (excluding deleted files)
    account_pipeline = [
        {
            "$match": {
                "backup_status": BackupStatus.COMPLETED, 
                "backup_location": StorageLocation.HETZNER,
                "deleted_at": {"$exists": False}  # Exclude deleted files
            }
        },
        {"$group": {
            "_id": "$gdrive_account_id",
            "count": {"$sum": 1},
            "total_size": {"$sum": "$size_bytes"}
        }},
        {"$sort": {"count": -1}}
    ]
    
    account_results = list(db.files.aggregate(account_pipeline))
    account_distribution = []
    for item in account_results:
        account_distribution.append({
            "account_id": item["_id"],
            "count": item["count"],
            "total_size": item["total_size"],
            "size_formatted": format_file_size(item["total_size"])
        })
    
    return {
        "file_types": file_types,
        "total_files": total_files,
        "backup_timeline": backup_timeline,
        "account_distribution": account_distribution
    }

@router.post("/hetzner/delete-all-files")
async def delete_all_hetzner_files(
    request: Request,
    reason: Optional[str] = Query(None),
    force_delete: Optional[bool] = Query(False),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """
    DANGEROUS OPERATION: Delete ALL files from Hetzner storage
    This will permanently remove all data from Hetzner backup storage
    
    force_delete: If True, skips storage scanning and deletes directly
    """
    try:
        print(f"🚨 [DELETE_ALL_HETZNER] Admin {current_admin.email} requested complete Hetzner storage cleanup!")
        print(f"🚨 [DELETE_ALL_HETZNER] Reason: {reason or 'No reason provided'}")
        print(f"🚨 [DELETE_ALL_HETZNER] Force delete: {force_delete}")
        
        from app.services.hetzner_service import HetznerService
        
        if force_delete:
            print(f"[DELETE_ALL_HETZNER] FORCE DELETE MODE: Skipping database check and storage scanning!")
            hetzner_service = HetznerService()
            deletion_result = await hetzner_service.delete_all_files_force()
        else:
            # Normal mode - check database first
            hetzner_stats_before = db.files.count_documents({
                "backup_status": BackupStatus.COMPLETED,
                "backup_location": StorageLocation.HETZNER,
                "deleted_at": {"$exists": False}
            })
            
            if hetzner_stats_before == 0:
                return {
                    "message": "No files found in Hetzner storage - already empty",
                    "deleted_files": 0,
                    "deleted_dirs": 0,
                    "errors": 0,
                    "total_items": 0,
                    "storage_cleaned": "0 B"
                }
            
            print(f"[DELETE_ALL_HETZNER] Found {hetzner_stats_before} files in database before deletion")
            
            hetzner_service = HetznerService()
            deletion_result = await hetzner_service.delete_all_files()
        
        if force_delete:
            # Force delete mode - skip database updates and use deletion result directly
            print(f"[DELETE_ALL_HETZNER] FORCE DELETE MODE: Skipping database updates")
            
            await log_admin_activity(
                admin_email=current_admin.email,
                action="force_delete_all_hetzner_files",
                details=f"Force deleted all files from Hetzner storage. Hetzner: {deletion_result.get('deleted_files', 0)} files, {deletion_result.get('deleted_dirs', 0)} dirs. Reason: {reason or 'Force storage cleanup'}",
                ip_address=get_client_ip(request),
                endpoint="/api/v1/admin/hetzner/delete-all-files"
            )
            
            response_data = {
                "message": deletion_result.get("message", "Force delete completed"),
                "deleted_files": deletion_result.get("deleted_files", 0),
                "deleted_dirs": deletion_result.get("deleted_dirs", 0),
                "errors": deletion_result.get("errors", 0),
                "total_items": deletion_result.get("total_items", 0),
                "database_records_updated": 0,  # No database updates in force mode
                "storage_cleaned": "Force delete completed",
                "storage_info_before": deletion_result.get("storage_info_before", {}),
                "storage_info_after": deletion_result.get("storage_info_after", {})
            }
        else:
            # Normal mode - update database records
            update_result = db.files.update_many(
                {
                    "backup_status": BackupStatus.COMPLETED,
                    "backup_location": StorageLocation.HETZNER,
                    "deleted_at": {"$exists": False}
                },
                {
                    "$set": {
                        "deleted_at": datetime.utcnow(),
                        "status": "deleted",
                        "deleted_by": current_admin.email,
                        "deletion_reason": f"bulk_delete_all_hetzner_files: {reason or 'Complete storage cleanup'}"
                    }
                }
            )
            
            print(f"[DELETE_ALL_HETZNER] Database update result: {update_result.modified_count} files marked as deleted")
            
            await log_admin_activity(
                admin_email=current_admin.email,
                action="delete_all_hetzner_files",
                details=f"Deleted all files from Hetzner storage. Hetzner: {deletion_result.get('deleted_files', 0)} files, {deletion_result.get('deleted_dirs', 0)} dirs, Database: {update_result.modified_count} records marked as deleted. Reason: {reason or 'Complete storage cleanup'}",
                ip_address=get_client_ip(request),
                endpoint="/api/v1/admin/hetzner/delete-all-files"
            )
            
            response_data = {
                "message": deletion_result.get("message", "Hetzner storage cleanup completed"),
                "deleted_files": deletion_result.get("deleted_files", 0),
                "deleted_dirs": deletion_result.get("deleted_dirs", 0),
                "errors": deletion_result.get("errors", 0),
                "total_items": deletion_result.get("total_items", 0),
                "database_records_updated": update_result.modified_count,
                "storage_cleaned": f"{hetzner_stats_before} files removed from backup storage",
                "storage_info_before": deletion_result.get("storage_info_before", {}),
                "storage_info_after": deletion_result.get("storage_info_after", {})
            }
        
        print(f"✅ [DELETE_ALL_HETZNER] Complete Hetzner storage cleanup finished: {response_data}")
        return response_data
        
    except Exception as e:
        error_msg = f"Failed to delete all Hetzner files: {str(e)}"
        print(f"!!! [DELETE_ALL_HETZNER] {error_msg}")
        
        try:
            await log_admin_activity(
                admin_email=current_admin.email,
                action="delete_all_hetzner_files_failed",
                details=f"Failed to delete all Hetzner files: {str(e)}",
                ip_address=get_client_ip(request),
                endpoint="/api/v1/admin/hetzner/delete-all-files"
            )
        except:
            pass
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg
        )

@router.post("/hetzner/parallel-cleanup")
async def parallel_hetzner_cleanup(
    request: Request,
    reason: Optional[str] = Query(None),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """
    HYBRID PARALLEL APPROACH: Fast parallel scanning + parallel deletion + database cleanup
    Uses 5 workers for both scanning and deletion
    Also cleans database records for complete cleanup
    Reduces 10+ minutes to ~3-4 minutes total
    """
    try:
        print(f"🚀 [PARALLEL_HETZNER] Admin {current_admin.email} requested parallel Hetzner storage cleanup!")
        print(f"🚀 [PARALLEL_HETZNER] Reason: {reason or 'No reason provided'}")
        print(f"🚀 [PARALLEL_HETZNER] Using 5 workers for scanning + 5 workers for deletion + database cleanup")
        
        from app.services.hetzner_service import HetznerService
        
        hetzner_service = HetznerService()
        
        # STEP 1: Fast parallel cleanup from Hetzner storage
        cleanup_result = await hetzner_service.parallel_storage_cleanup()
        
        # STEP 2: Clean database records
        print(f"[PARALLEL_HETZNER] Cleaning database records...")
        update_result = db.files.update_many(
            {
                "backup_status": BackupStatus.COMPLETED,
                "backup_location": StorageLocation.HETZNER,
                "deleted_at": {"$exists": False}
            },
            {
                "$set": {
                    "deleted_at": datetime.utcnow(),
                    "status": "deleted",
                    "deleted_by": current_admin.email,
                    "deletion_reason": f"parallel_cleanup: {reason or 'Fast parallel storage cleanup'}"
                }
            }
        )
        
        print(f"[PARALLEL_HETZNER] Database cleanup result: {update_result.modified_count} records marked as deleted")
        
        # Log the complete parallel cleanup activity
        await log_admin_activity(
            admin_email=current_admin.email,
            action="parallel_hetzner_cleanup_complete",
            details=f"Complete parallel cleanup: Hetzner: {cleanup_result.get('deleted_files', 0)} files, {cleanup_result.get('deleted_dirs', 0)} dirs, Time: {cleanup_result.get('total_time', 0):.2f}s, Workers: {cleanup_result.get('workers_used', 5)}, Database: {update_result.modified_count} records cleaned. Reason: {reason or 'Fast parallel storage cleanup'}",
            ip_address=get_client_ip(request),
            endpoint="/api/v1/admin/hetzner/parallel-cleanup"
        )
        
        response_data = {
            "message": f"Complete parallel cleanup finished: {cleanup_result.get('deleted_files', 0)} files deleted in {cleanup_result.get('total_time', 0):.2f}s",
            "deleted_files": cleanup_result.get("deleted_files", 0),
            "deleted_dirs": cleanup_result.get("deleted_dirs", 0),
            "errors": cleanup_result.get("errors", 0),
            "total_items": cleanup_result.get("total_items", 0),
            "scan_time": cleanup_result.get("scan_time", 0),
            "delete_time": cleanup_result.get("delete_time", 0),
            "total_time": cleanup_result.get("total_time", 0),
            "parallel_mode": cleanup_result.get("parallel_mode", True),
            "workers_used": cleanup_result.get("workers_used", 5),
            "performance_improvement": "5x faster than sequential operations",
            "database_records_cleaned": update_result.modified_count,
            "complete_cleanup": True
        }
        
        print(f"🚀 [PARALLEL_HETZNER] Complete parallel Hetzner storage cleanup finished: {response_data}")
        return response_data
        
    except Exception as e:
        error_msg = f"Failed to perform parallel Hetzner cleanup: {str(e)}"
        print(f"!!! [PARALLEL_HETZNER] {error_msg}")
        
        try:
            await log_admin_activity(
                admin_email=current_admin.email,
                action="parallel_hetzner_cleanup_failed",
                details=f"Failed to perform parallel Hetzner cleanup: {str(e)}",
                ip_address=get_client_ip(request),
                endpoint="/api/v1/admin/hetzner/parallel-cleanup"
            )
        except:
            pass
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg
        )

@router.get("/hetzner/storage-info")
async def get_hetzner_storage_info(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """
    Get real-time storage information from Hetzner using parallel scanning
    This endpoint automatically uses 5 workers for faster scanning
    """
    try:
        print(f"[HETZNER_STORAGE_INFO] Admin {current_admin.email} requested Hetzner storage info")
        
        from app.services.hetzner_service import HetznerService
        
        hetzner_service = HetznerService()
        
        # Use the new parallel scanning method for faster results
        print(f"[HETZNER_STORAGE_INFO] Using parallel scanning with 5 workers for faster results")
        storage_info = await hetzner_service.auto_parallel_scan_with_progress()
        
        print(f"[HETZNER_STORAGE_INFO] Parallel scan completed: {storage_info}")
        
        # Log the activity
        await log_admin_activity(
            admin_email=current_admin.email,
            action="get_hetzner_storage_info",
            details=f"Retrieved Hetzner storage info using parallel scanning. Found {storage_info.get('total_files', 0)} files, {storage_info.get('total_size_formatted', '0 B')}",
            ip_address=get_client_ip(request),
            endpoint="/api/v1/admin/hetzner/storage-info"
        )
        
        return {
            "total_files": storage_info.get("total_files", 0),
            "total_size": storage_info.get("total_size", 0),
            "total_size_formatted": storage_info.get("total_size_formatted", "0 B"),
            "status": storage_info.get("status", "completed"),
            "progress": storage_info.get("progress", 100),
            "message": storage_info.get("message", "Storage info retrieved"),
            "parallel_mode": storage_info.get("parallel_mode", True),
            "workers_used": storage_info.get("workers_used", 5)
        }
        
    except Exception as e:
        error_msg = f"Failed to get Hetzner storage info: {str(e)}"
        print(f"!!! [HETZNER_STORAGE_INFO] {error_msg}")
        
        try:
            await log_admin_activity(
                admin_email=current_admin.email,
                action="get_hetzner_storage_info_failed",
                details=f"Failed to get Hetzner storage info: {str(e)}",
                ip_address=get_client_ip(request),
                endpoint="/api/v1/admin/hetzner/storage-info"
            )
        except:
            pass
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg
        )

# ================================
# BACKUP MANAGEMENT ENDPOINTS
# ================================

@router.get("/backup/status")
async def get_backup_status(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get Hetzner storage status and backup queue monitoring"""
    
    # Get backup statistics
    total_files = db.files.count_documents({})
    backed_up_files = db.files.count_documents({"backup_status": "completed"})
    in_progress_backups = db.files.count_documents({"backup_status": "in_progress"})
    failed_backups = db.files.count_documents({"backup_status": "failed"})
    
    # Get storage usage for backed up files
    backup_storage_pipeline = [
        {"$match": {"backup_status": "completed", "size_bytes": {"$exists": True}}},
        {"$group": {
            "_id": None,
            "total_backup_size": {"$sum": "$size_bytes"},
            "backup_count": {"$sum": 1}
        }}
    ]
    backup_storage = list(db.files.aggregate(backup_storage_pipeline))
    backup_size = backup_storage[0]["total_backup_size"] if backup_storage else 0
    
    # Test Hetzner connectivity
    hetzner_status = "unknown"
    try:
        from app.core.config import settings
        import httpx
        
        if all([settings.HETZNER_WEBDAV_URL, settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD]):
            auth = (settings.HETZNER_USERNAME, settings.HETZNER_PASSWORD)
            async with httpx.AsyncClient(auth=auth, timeout=10.0) as client:
                response = await client.request("PROPFIND", settings.HETZNER_WEBDAV_URL)
                if response.status_code in [200, 207, 404]:  # 404 is ok, means directory doesn't exist yet
                    hetzner_status = "connected"
                else:
                    hetzner_status = "error"
        else:
            hetzner_status = "not_configured"
    except Exception as e:
        hetzner_status = f"error: {str(e)}"
    
    # Get recent backup failures
    recent_failures = list(db.files.find(
        {"backup_status": "failed"},
        {"filename": 1, "backup_error": 1, "backup_failed_at": 1}
    ).sort("backup_failed_at", -1).limit(10))
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_backup_status",
        details="Viewed backup system status",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/backup/status"
    )
    
    return {
        "backup_summary": {
            "total_files": total_files,
            "backed_up_files": backed_up_files,
            "backup_percentage": round((backed_up_files / total_files * 100) if total_files > 0 else 0, 2),
            "in_progress": in_progress_backups,
            "failed": failed_backups,
            "total_backup_size": backup_size
        },
        "hetzner_status": hetzner_status,
        "recent_failures": recent_failures
    }

@router.get("/backup/queue")
async def get_backup_queue(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get backup queue monitoring"""
    
    skip = (page - 1) * limit
    
    # Get files pending backup or in progress
    queue_query = {
        "$or": [
            {"backup_status": "in_progress"},
            {"backup_status": "none"},
            {"backup_status": {"$exists": False}}
        ]
    }
    
    queue_files = list(db.files.find(
        queue_query,
        {
            "filename": 1, "size_bytes": 1, "upload_date": 1,
            "backup_status": 1, "backup_started_at": 1,
            "gdrive_account_id": 1, "user_id": 1
        }
    ).sort("upload_date", 1).skip(skip).limit(limit))
    
    total_queue = db.files.count_documents(queue_query)
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_backup_queue",
        details=f"Viewed backup queue - page {page}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/backup/queue"
    )
    
    return {
        "queue_files": queue_files,
        "total_in_queue": total_queue,
        "page": page,
        "limit": limit,
        "total_pages": (total_queue + limit - 1) // limit
    }

@router.post("/backup/trigger-mass")
async def trigger_mass_backup(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Trigger backup for multiple files that don't have backup"""
    
    from app.services import backup_service
    import asyncio
    
    # Find files without backup
    files_to_backup = list(db.files.find(
        {
            "$or": [
                {"backup_status": "none"},
                {"backup_status": {"$exists": False}},
                {"backup_status": "failed"}
            ],
            "status": "completed"  # Only backup completed uploads
        },
        {"_id": 1, "filename": 1}
    ).limit(50))  # Limit to 50 files at once
    
    backup_count = 0
    for file_doc in files_to_backup:
        try:
            # Mark as backup requested
            db.files.update_one(
                {"_id": file_doc["_id"]},
                {
                    "$set": {
                        "backup_status": "in_progress",
                        "backup_started_at": datetime.utcnow(),
                        "backup_requested_by": current_admin.email,
                        "backup_reason": "Mass backup trigger"
                    }
                }
            )
            
            # Start backup task
            asyncio.create_task(backup_service.transfer_gdrive_to_hetzner(file_doc["_id"]))
            backup_count += 1
            
        except Exception as e:
            print(f"Failed to start backup for {file_doc['_id']}: {e}")
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="trigger_mass_backup",
        details=f"Triggered backup for {backup_count} files",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/backup/trigger-mass"
    )
    
    return {
        "message": f"Triggered backup for {backup_count} files",
        "files_initiated": backup_count
    }

@router.get("/backup/failures")
async def get_backup_failures(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    days: int = Query(30, ge=1, le=365),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get backup failure logs and analysis"""
    
    skip = (page - 1) * limit
    since_date = datetime.utcnow() - timedelta(days=days)
    
    # Get failed backups
    failed_backups = list(db.files.find(
        {
            "backup_status": "failed",
            "backup_failed_at": {"$gte": since_date}
        },
        {
            "filename": 1, "size_bytes": 1, "backup_error": 1,
            "backup_failed_at": 1, "gdrive_account_id": 1,
            "user_id": 1, "content_type": 1
        }
    ).sort("backup_failed_at", -1).skip(skip).limit(limit))
    
    total_failures = db.files.count_documents({
        "backup_status": "failed",
        "backup_failed_at": {"$gte": since_date}
    })
    
    # Analyze failure patterns
    failure_by_error = list(db.files.aggregate([
        {
            "$match": {
                "backup_status": "failed",
                "backup_failed_at": {"$gte": since_date}
            }
        },
        {
            "$group": {
                "_id": "$backup_error",
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]))
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_backup_failures",
        details=f"Viewed backup failures for {days} days - page {page}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/backup/failures"
    )
    
    return {
        "failed_backups": failed_backups,
        "total_failures": total_failures,
        "failure_patterns": failure_by_error,
        "page": page,
        "limit": limit,
        "total_pages": (total_failures + limit - 1) // limit,
        "period_days": days
    }

@router.post("/backup/cleanup")
async def backup_cleanup(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Storage cleanup tools - remove old failed backups and reset status"""
    
    # Reset old failed backups (older than 7 days) to allow retry
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    
    reset_result = db.files.update_many(
        {
            "backup_status": "failed",
            "backup_failed_at": {"$lt": seven_days_ago}
        },
        {
            "$set": {
                "backup_status": "none",
                "backup_reset_at": datetime.utcnow(),
                "backup_reset_by": current_admin.email
            },
            "$unset": {
                "backup_error": "",
                "backup_failed_at": ""
            }
        }
    )
    
    # Clean up orphaned backup status (files that don't exist in gdrive anymore)
    orphaned_count = 0
    orphaned_files = list(db.files.find(
        {"backup_status": "in_progress", "backup_started_at": {"$lt": seven_days_ago}},
        {"_id": 1, "filename": 1}
    ))
    
    for file_doc in orphaned_files:
        db.files.update_one(
            {"_id": file_doc["_id"]},
            {
                "$set": {
                    "backup_status": "failed",
                    "backup_error": "Backup timeout - reset by cleanup",
                    "backup_failed_at": datetime.utcnow()
                }
            }
        )
        orphaned_count += 1
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="backup_cleanup",
        details=f"Reset {reset_result.modified_count} failed backups, cleaned {orphaned_count} stuck backups",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/backup/cleanup"
    )
    
    return {
        "message": "Backup cleanup completed",
        "reset_failed_backups": reset_result.modified_count,
        "cleaned_stuck_backups": orphaned_count
    }