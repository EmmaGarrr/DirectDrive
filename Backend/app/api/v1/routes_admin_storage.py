from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
import json

from app.services.admin_auth_service import (
    get_current_admin,
    log_admin_activity,
    get_client_ip,
)
from app.models.admin import AdminUserInDB
from app.db.mongodb import db
from app.services.google_drive_service import gdrive_pool_manager
from app.services.google_drive_account_service import (
    GoogleDriveAccountService,
)
from app.models.google_drive_account import GoogleDriveAccountCreate

router = APIRouter()

# Pydantic models for storage management
class GoogleDriveAccountInfo(BaseModel):
    account_id: str
    email: str
    is_active: bool
    storage_used: int
    storage_quota: int
    files_count: int
    last_activity: Optional[datetime]
    health_status: str
    performance_score: float

class StorageQuotaUpdate(BaseModel):
    quota_limit: int  # in bytes
    warning_threshold: float = 0.8  # percentage (0.8 = 80%)

class LoadBalancingConfig(BaseModel):
    algorithm: str  # 'round_robin', 'least_used', 'performance_based'
    weight_factors: Dict[str, float]
    enable_auto_failover: bool = True

class AccountCredentials(BaseModel):
    service_account_key: str  # JSON string of service account key
    account_email: str
    account_alias: str

@router.get("/storage/google-drive/accounts")
async def list_google_drive_accounts(
    request: Request,
    refresh: bool = Query(False, description="Force refresh from Google Drive API"),
    current_admin: AdminUserInDB = Depends(get_current_admin),
):
    """List all Google Drive accounts with their status and usage (smart cached data)."""

    # Fetch accounts from DB
    accounts = await GoogleDriveAccountService.get_all_accounts()
    
    # Smart caching logic: Only refresh if explicitly requested or if data is very stale (>15 minutes)
    cache_expiry_seconds = 900  # 15 minutes
    needs_refresh = refresh
    cache_status = "fresh"
    
    if not refresh:
        # Check if any account data is stale using consistent timezone handling
        current_time = datetime.now()
        for account in accounts:
            if account.last_quota_check:
                # Convert UTC timestamp to local time for consistent comparison
                local_quota_check = account.last_quota_check.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
                time_diff = (current_time - local_quota_check).total_seconds()
                if time_diff > cache_expiry_seconds:
                    needs_refresh = True
                    cache_status = "stale"
                    break
    
    # Perform refresh if needed
    if needs_refresh:
        try:
            for account in accounts:
                if account.is_active:
                    try:
                        await GoogleDriveAccountService._update_account_quota(account)
                    except Exception as e:
                        print(f"Failed to refresh account {account.account_id}: {e}")
            
            # Re-fetch accounts after refresh
            accounts = await GoogleDriveAccountService.get_all_accounts()
            cache_status = "fresh"
        except Exception as e:
            print(f"Error during bulk refresh: {e}")
            cache_status = "error"

    account_responses = []
    for acc in accounts:
        response_data = GoogleDriveAccountService.to_response_model(acc).dict()
        
        # Add folder information and freshness indicator
        response_data["folder_info"] = {
            "folder_id": acc.folder_id,
            "folder_name": acc.folder_name or "Root",
            "folder_path": acc.folder_path or "/",
        }
        # Fix: Use consistent local time for all timestamp calculations
        if acc.last_quota_check:
            # Convert UTC timestamp to local time for consistent display
            local_quota_check = acc.last_quota_check.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
            response_data["last_quota_check"] = local_quota_check.isoformat()
            
            # Calculate data freshness using local time - use same threshold as header cache (15 minutes)
            current_time = datetime.now()
            time_diff = (current_time - local_quota_check).total_seconds()
            response_data["data_freshness"] = "fresh" if time_diff < 900 else "stale"  # 15 minutes = 900 seconds (same as cache_expiry_seconds)
        else:
            response_data["last_quota_check"] = None
            response_data["data_freshness"] = "stale"
        
        account_responses.append(response_data)

    # Aggregated statistics
    stats = await GoogleDriveAccountService.get_account_statistics()
    statistics = {
        "total_accounts": len(accounts),
        "active_accounts": stats.get("active_accounts", 0),
        "total_storage_used": stats.get("total_storage_used", 0),
        "total_storage_quota": stats.get("total_storage_quota", 0),
        "average_performance": stats.get("average_performance", 0),
    }

    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_gdrive_accounts",
        details=f"Viewed Google Drive accounts list (refresh={refresh}, cache_status={cache_status})",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/storage/google-drive/accounts",
    )

    return {
        "accounts": account_responses, 
        "statistics": statistics,
        "cache_info": {
            "status": cache_status,
            "last_updated": datetime.now().isoformat(),
            "cache_expiry_seconds": cache_expiry_seconds,
            "is_forced_refresh": refresh
        }
    }

@router.get("/storage/google-drive/accounts/{account_id}")
async def get_google_drive_account_detail(
    account_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin),
):
    """Get detailed information about a specific Google Drive account (real data)."""

    account = await GoogleDriveAccountService.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    # Ensure quota and folder info is fresh
    try:
        await GoogleDriveAccountService._update_account_quota(account)  # type: ignore
    except Exception:
        pass

    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_gdrive_account_detail",
        details=f"Viewed detailed info for Google Drive account: {account_id}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/storage/google-drive/accounts/{account_id}",
    )

    return GoogleDriveAccountService.to_response_model(account)

@router.post("/storage/google-drive/accounts/{account_id}/toggle")
async def toggle_google_drive_account(
    account_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin),
):
    """Enable or disable a Google Drive account (real)."""

    updated = await GoogleDriveAccountService.toggle_account_status(account_id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    await log_admin_activity(
        admin_email=current_admin.email,
        action="gdrive_account_toggle",
        details=f"Toggled Google Drive account: {account_id} -> is_active={updated.is_active}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/storage/google-drive/accounts/{account_id}/toggle",
    )

    # Reload the pool so toggle takes effect for uploads
    try:
        await gdrive_pool_manager.reload_from_db()  # type: ignore
    except Exception as e:
        print(f"[ADMIN_STORAGE] Pool reload failed after toggle: {e}")

    return {"message": "Account status updated", "account_id": account_id, "is_active": updated.is_active}

@router.post("/storage/google-drive/accounts")
async def add_google_drive_account(
    credentials: AccountCredentials,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin),
):
    """Add a new Google Drive account (service account or OAuth)."""

    # Validate JSON early
    try:
        json.loads(credentials.service_account_key)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON format for service account key"
        )

    try:
        created = await GoogleDriveAccountService.create_account(
            GoogleDriveAccountCreate(
                email=credentials.account_email,
                alias=credentials.account_alias,
                service_account_key=credentials.service_account_key,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to add account: {e}")

    await log_admin_activity(
        admin_email=current_admin.email,
        action="add_gdrive_account",
        details=f"Added new Google Drive account: {credentials.account_alias} ({credentials.account_email})",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/storage/google-drive/accounts",
    )

    # Reload the pool so the new account can be selected immediately
    try:
        await gdrive_pool_manager.reload_from_db()  # type: ignore
    except Exception as e:
        print(f"[ADMIN_STORAGE] Pool reload failed after add: {e}")

    return {
        "message": "Google Drive account added successfully",
        "account_id": created.account_id,
        "account_email": created.email,
        "account_alias": created.alias,
    }

@router.delete("/storage/google-drive/accounts/{account_id}")
async def remove_google_drive_account(
    account_id: str,
    request: Request,
    force: bool = Query(False, description="Force removal even if account has files"),
    current_admin: AdminUserInDB = Depends(get_current_admin),
):
    """Remove a Google Drive account (real)."""

    try:
        deleted = await GoogleDriveAccountService.delete_account(account_id, force=force)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    await log_admin_activity(
        admin_email=current_admin.email,
        action="remove_gdrive_account",
        details=f"Removed Google Drive account: {account_id} (force={force})",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/storage/google-drive/accounts/{account_id}",
    )

    # Reload the pool so the removed account is no longer used
    try:
        await gdrive_pool_manager.reload_from_db()  # type: ignore
    except Exception as e:
        print(f"[ADMIN_STORAGE] Pool reload failed after remove: {e}")

    return {"message": f"Google Drive account {account_id} removed successfully"}

@router.post("/storage/google-drive/accounts/{account_id}/delete-all-files")
async def delete_all_files_from_account(
    account_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin),
):
    """Delete all files from a specific Google Drive account folder"""
    
    try:
        print(f"🗑️ [DELETE_ALL_FILES] Starting deletion for account: {account_id}")
        
        # Get the account
        account = await GoogleDriveAccountService.get_account_by_id(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Google Drive account not found")
        
        # Delete all files in the account's folder
        result = await GoogleDriveAccountService.delete_all_files_in_account_folder(account)
        
        # Also soft-delete all related files in MongoDB for this account
        soft_delete_result = db.files.update_many(
            {"gdrive_account_id": account_id, "deleted_at": {"$exists": False}},
            {"$set": {
                "deleted_at": datetime.now(),
                "status": "deleted", 
                "deleted_by": current_admin.email,
                "deletion_reason": f"bulk_delete_account_{account_id}"
            }}
        )
        
        print(f"🗑️ [DELETE_ALL_FILES] Account {account_id}: GDrive deleted={result.get('deleted', 0)}, MongoDB soft-deleted={soft_delete_result.modified_count}")
        
        await log_admin_activity(
            admin_email=current_admin.email,
            action="delete_all_account_files",
            details=f"Deleted all files from Google Drive account {account_id}. GDrive: {result.get('deleted', 0)} files, MongoDB: {soft_delete_result.modified_count} records",
            ip_address=get_client_ip(request),
            endpoint=f"/api/v1/admin/storage/google-drive/accounts/{account_id}/delete-all-files",
        )
        
        return {
            "message": f"All files deleted from account {account_id}",
            "gdrive_deleted": result.get("deleted", 0),
            "gdrive_errors": result.get("errors", 0),
            "mongodb_soft_deleted": soft_delete_result.modified_count,
            "details": result
        }
        
    except Exception as e:
        print(f"🗑️ [DELETE_ALL_FILES] Error for account {account_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete files: {str(e)}")

@router.post("/storage/google-drive/accounts/{account_id}/refresh-stats")
async def refresh_account_stats(
    account_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin),
):
    """Manually refresh stats for a specific Google Drive account"""
    
    try:
        print(f"🔄 [REFRESH_STATS] Refreshing stats for account: {account_id}")
        
        # Get the account
        account = await GoogleDriveAccountService.get_account_by_id(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Google Drive account not found")
        
        # Force refresh account quota and file counts from Google Drive API
        await GoogleDriveAccountService._update_account_quota(account)
        
        # Get updated account data
        updated_account = await GoogleDriveAccountService.get_account_by_id(account_id)
        
        print(f"🔄 [REFRESH_STATS] Account {account_id} refreshed: {updated_account.files_count} files, {updated_account.storage_used} bytes")
        
        await log_admin_activity(
            admin_email=current_admin.email,
            action="refresh_account_stats",
            details=f"Manually refreshed stats for Google Drive account {account_id}",
            ip_address=get_client_ip(request),
            endpoint=f"/api/v1/admin/storage/google-drive/accounts/{account_id}/refresh-stats",
        )
        
        return {
            "message": f"Stats refreshed for account {account_id}",
            "files_count": updated_account.files_count,
            "storage_used": updated_account.storage_used,
            "storage_quota": updated_account.storage_quota,
            "storage_used_formatted": GoogleDriveAccountService.format_storage_size(updated_account.storage_used),
            "storage_quota_formatted": GoogleDriveAccountService.format_storage_size(updated_account.storage_quota)
        }
        
    except Exception as e:
        print(f"🔄 [REFRESH_STATS] Error for account {account_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to refresh stats: {str(e)}")

@router.get("/storage/google-drive/load-balancing")
async def get_load_balancing_config(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get current load balancing configuration"""
    
    # Mock current configuration
    config = {
        "algorithm": "least_used",
        "weight_factors": {
            "storage_usage": 0.4,
            "performance_score": 0.3,
            "response_time": 0.2,
            "failure_rate": 0.1
        },
        "enable_auto_failover": True,
        "failover_threshold": {
            "max_failures": 5,
            "time_window_minutes": 15,
            "recovery_time_minutes": 30
        },
        "health_check_interval": 300,  # seconds
        "last_updated": datetime.now() - timedelta(days=2),
        "updated_by": "system@directdrive.com"
    }
    
    # Current account loads
    account_loads = [
        {
            "account_id": "account_1",
            "current_load": 78.5,
            "active_uploads": 12,
            "queue_size": 3,
            "weight": 1.0
        },
        {
            "account_id": "account_2", 
            "current_load": 45.2,
            "active_uploads": 7,
            "queue_size": 1,
            "weight": 1.2
        },
        {
            "account_id": "account_3",
            "current_load": 95.8,
            "active_uploads": 2,
            "queue_size": 8,
            "weight": 0.5
        }
    ]
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_load_balancing_config",
        details="Viewed load balancing configuration",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/storage/google-drive/load-balancing"
    )
    
    return {
        "configuration": config,
        "current_loads": account_loads,
        "statistics": {
            "total_active_uploads": sum(load["active_uploads"] for load in account_loads),
            "total_queue_size": sum(load["queue_size"] for load in account_loads),
            "average_load": sum(load["current_load"] for load in account_loads) / len(account_loads)
        }
    }

@router.put("/storage/google-drive/load-balancing")
async def update_load_balancing_config(
    config: LoadBalancingConfig,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Update load balancing configuration"""
    
    # Validate configuration
    valid_algorithms = ["round_robin", "least_used", "performance_based"]
    if config.algorithm not in valid_algorithms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid algorithm. Must be one of: {', '.join(valid_algorithms)}"
        )
    
    # Validate weight factors sum to 1.0
    if abs(sum(config.weight_factors.values()) - 1.0) > 0.01:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Weight factors must sum to 1.0"
        )
    
    # Mock configuration update
    # In production, this would update the actual load balancer
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="update_load_balancing",
        details=f"Updated load balancing: algorithm={config.algorithm}, auto_failover={config.enable_auto_failover}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/storage/google-drive/load-balancing"
    )
    
    return {
        "message": "Load balancing configuration updated successfully",
        "configuration": config.dict(),
        "updated_at": datetime.now(),
        "updated_by": current_admin.email
    }

@router.post("/storage/google-drive/accounts/{account_id}/health-check")
async def perform_health_check(
    account_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin),
):
    """Perform manual health check on a Google Drive account (real connectivity check)."""

    account = await GoogleDriveAccountService.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    status_label = "healthy"
    details: Dict[str, Any] = {}
    try:
        # Try updating quota and folder meta as a health probe
        await GoogleDriveAccountService._update_account_quota(account)  # type: ignore
        details["quota_check"] = "ok"
    except Exception as e:
        status_label = "unhealthy"
        details["quota_check"] = f"error: {e}"

    await log_admin_activity(
        admin_email=current_admin.email,
        action="gdrive_health_check",
        details=f"Performed health check on account {account_id}: {status_label}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/storage/google-drive/accounts/{account_id}/health-check",
    )

    return {
        "account_id": account_id,
        "overall_status": status_label,
        "check_timestamp": datetime.now(),
        "details": details,
    }

@router.post("/storage/google-drive/reset-all")
async def reset_all_storage(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin),
    hard: bool = Query(False, description="If true, hard-delete all file and batch records from Mongo")
):
    """Dangerous operation: Delete all files under configured Google Drive folders for all accounts
    and reset all file metadata in MongoDB (soft-delete) with optional hard purge.
    """
    try:
        # 1) Delete files from Google Drive folders for all accounts
        gdrive_result = await GoogleDriveAccountService.delete_all_files_all_accounts()

        # 2) Reset MongoDB file records
        if hard:
            files_deleted = db.files.delete_many({})
            batches_deleted = db.batches.delete_many({})
            files_marked_deleted = 0
        else:
            # Mark all files as deleted and set deleted_at to now
            deleted_mark = db.files.update_many(
                {"deleted_at": {"$exists": False}},
                {"$set": {"deleted_at": datetime.now(), "status": "deleted", "deletion_reason": "reset_all_storage"}}
            )
            # Also clear batches to avoid dangling references
            batches_deleted = db.batches.delete_many({})
            files_deleted = None
            files_marked_deleted = deleted_mark.modified_count

        # 3) Reset account stats by forcing quota refresh
        await GoogleDriveAccountService.update_all_accounts_quota()

        await log_admin_activity(
            admin_email=current_admin.email,
            action="reset_all_storage",
            details=f"Reset storage and metadata. GDrive result: {gdrive_result['summary']}",
            ip_address=get_client_ip(request),
            endpoint="/api/v1/admin/storage/google-drive/reset-all",
        )

        return {
            "message": "All storage reset initiated and metadata cleared",
            "gdrive": gdrive_result,
            "files_marked_deleted": files_marked_deleted,
            "files_hard_deleted": (files_deleted.deleted_count if files_deleted else 0),
            "batches_deleted": batches_deleted.deleted_count,
            "mode": "hard" if hard else "soft"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {e}")

@router.get("/storage/google-drive/combined-stats")
async def get_combined_google_drive_stats(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin),
):
    """Get combined Google Drive storage statistics for dashboard"""
    
    # Get aggregated statistics from all accounts
    stats = await GoogleDriveAccountService.get_account_statistics()
    
    # Calculate available storage
    total_quota = stats.get("total_storage_quota", 0)
    total_used = stats.get("total_storage_used", 0)
    available_storage = max(0, total_quota - total_used)
    
    # Calculate usage percentage
    usage_percentage = (total_used / total_quota * 100) if total_quota > 0 else 0
    
    # Format storage sizes
    combined_stats = {
        "total_accounts": stats.get("total_accounts", 0),
        "active_accounts": stats.get("active_accounts", 0),
        "total_storage_quota": total_quota,
        "total_storage_quota_formatted": format_storage_size(total_quota),
        "total_storage_used": total_used,
        "total_storage_used_formatted": format_storage_size(total_used),
        "available_storage": available_storage,
        "available_storage_formatted": format_storage_size(available_storage),
        "usage_percentage": round(usage_percentage, 1),
        "health_status": "good" if usage_percentage < 80 else "warning" if usage_percentage < 95 else "critical"
    }
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_gdrive_combined_stats",
        details="Viewed combined Google Drive storage statistics",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/storage/google-drive/combined-stats",
    )
    
    return combined_stats

def format_storage_size(bytes_size: int) -> str:
    """Format storage size in human readable format"""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.1f} MB"
    elif bytes_size < 1024 * 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024 * 1024):.1f} GB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024 * 1024):.1f} TB"