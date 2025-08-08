from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from app.services.admin_auth_service import get_current_admin, log_admin_activity, get_client_ip
from app.models.admin import AdminUserInDB
from app.db.mongodb import db
from app.services.google_drive_service import gdrive_pool_manager
from pydantic import BaseModel, EmailStr
import json

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
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """List all Google Drive accounts with their status and usage"""
    
    # Get account information from the pool manager
    accounts_info = []
    
    # Mock implementation - in production, this would query actual Google Drive accounts
    mock_accounts = [
        {
            "account_id": "account_1",
            "email": "storage1@directdrive.service.com",
            "is_active": True,
            "storage_used": 450 * 1024 * 1024 * 1024,  # 450GB
            "storage_quota": 15 * 1024 * 1024 * 1024 * 1024,  # 15TB
            "files_count": 603,
            "last_activity": datetime.utcnow() - timedelta(minutes=5),
            "health_status": "healthy",
            "performance_score": 95.2
        },
        {
            "account_id": "account_2", 
            "email": "storage2@directdrive.service.com",
            "is_active": True,
            "storage_used": 280 * 1024 * 1024 * 1024,  # 280GB
            "storage_quota": 15 * 1024 * 1024 * 1024 * 1024,  # 15TB
            "files_count": 387,
            "last_activity": datetime.utcnow() - timedelta(minutes=2),
            "health_status": "healthy",
            "performance_score": 87.8
        },
        {
            "account_id": "account_3",
            "email": "storage3@directdrive.service.com", 
            "is_active": False,
            "storage_used": 1.2 * 1024 * 1024 * 1024 * 1024,  # 1.2TB
            "storage_quota": 15 * 1024 * 1024 * 1024 * 1024,  # 15TB
            "files_count": 150,
            "last_activity": datetime.utcnow() - timedelta(hours=2),
            "health_status": "quota_warning",
            "performance_score": 45.3
        }
    ]
    
    # Enrich with calculated metrics
    for account in mock_accounts:
        account["storage_used_formatted"] = format_storage_size(account["storage_used"])
        account["storage_quota_formatted"] = format_storage_size(account["storage_quota"])
        account["storage_percentage"] = (account["storage_used"] / account["storage_quota"]) * 100
        account["average_file_size"] = account["storage_used"] / max(account["files_count"], 1)
        account["average_file_size_formatted"] = format_storage_size(account["average_file_size"])
        
        # Health status logic
        if account["storage_percentage"] > 90:
            account["health_status"] = "critical"
        elif account["storage_percentage"] > 80:
            account["health_status"] = "warning"
        elif not account["is_active"]:
            account["health_status"] = "inactive"
        else:
            account["health_status"] = "healthy"
    
    # Overall statistics
    total_storage_used = sum(account["storage_used"] for account in mock_accounts)
    total_storage_quota = sum(account["storage_quota"] for account in mock_accounts)
    active_accounts = sum(1 for account in mock_accounts if account["is_active"])
    
    statistics = {
        "total_accounts": len(mock_accounts),
        "active_accounts": active_accounts,
        "inactive_accounts": len(mock_accounts) - active_accounts,
        "total_storage_used": total_storage_used,
        "total_storage_used_formatted": format_storage_size(total_storage_used),
        "total_storage_quota": total_storage_quota,
        "total_storage_quota_formatted": format_storage_size(total_storage_quota),
        "overall_usage_percentage": (total_storage_used / total_storage_quota) * 100,
        "total_files": sum(account["files_count"] for account in mock_accounts)
    }
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_gdrive_accounts",
        details="Viewed Google Drive accounts list",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/storage/google-drive/accounts"
    )
    
    return {
        "accounts": mock_accounts,
        "statistics": statistics
    }

@router.get("/storage/google-drive/accounts/{account_id}")
async def get_google_drive_account_detail(
    account_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get detailed information about a specific Google Drive account"""
    
    # Mock detailed account information
    account_details = {
        "account_id": account_id,
        "email": f"storage{account_id.split('_')[1]}@directdrive.service.com",
        "is_active": True,
        "created_at": datetime.utcnow() - timedelta(days=45),
        "last_health_check": datetime.utcnow() - timedelta(minutes=5),
        "storage_metrics": {
            "used": 450 * 1024 * 1024 * 1024,
            "quota": 15 * 1024 * 1024 * 1024 * 1024,
            "available": 14.6 * 1024 * 1024 * 1024 * 1024,
            "usage_percentage": 3.0
        },
        "performance_metrics": {
            "upload_success_rate": 96.8,
            "average_upload_speed": 50.2,  # MB/s
            "last_week_uploads": 245,
            "last_week_failures": 8,
            "response_time_ms": 150
        },
        "files_statistics": {
            "total_files": 603,
            "by_type": {
                "images": 245,
                "documents": 167,
                "videos": 89,
                "archives": 78,
                "others": 24
            }
        },
        "recent_activity": [
            {
                "timestamp": datetime.utcnow() - timedelta(minutes=5),
                "action": "file_upload",
                "file_name": "presentation.pdf",
                "file_size": 12 * 1024 * 1024,
                "status": "success"
            },
            {
                "timestamp": datetime.utcnow() - timedelta(minutes=15),
                "action": "file_upload", 
                "file_name": "video.mp4",
                "file_size": 156 * 1024 * 1024,
                "status": "success"
            },
            {
                "timestamp": datetime.utcnow() - timedelta(hours=1),
                "action": "health_check",
                "details": "Account health verification",
                "status": "healthy"
            }
        ]
    }
    
    # Format sizes
    metrics = account_details["storage_metrics"]
    metrics["used_formatted"] = format_storage_size(metrics["used"])
    metrics["quota_formatted"] = format_storage_size(metrics["quota"])
    metrics["available_formatted"] = format_storage_size(metrics["available"])
    
    # Format activity file sizes
    for activity in account_details["recent_activity"]:
        if "file_size" in activity:
            activity["file_size_formatted"] = format_storage_size(activity["file_size"])
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_gdrive_account_detail",
        details=f"Viewed detailed info for Google Drive account: {account_id}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/storage/google-drive/accounts/{account_id}"
    )
    
    return account_details

@router.post("/storage/google-drive/accounts/{account_id}/toggle")
async def toggle_google_drive_account(
    account_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Enable or disable a Google Drive account"""
    
    # Mock implementation - in production, this would update the actual account status
    new_status = True  # This would be determined by current status
    
    # Log admin activity
    action = "enable" if new_status else "disable"
    await log_admin_activity(
        admin_email=current_admin.email,
        action=f"gdrive_account_{action}",
        details=f"{'Enabled' if new_status else 'Disabled'} Google Drive account: {account_id}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/storage/google-drive/accounts/{account_id}/toggle"
    )
    
    return {
        "message": f"Account {account_id} {'enabled' if new_status else 'disabled'} successfully",
        "account_id": account_id,
        "is_active": new_status
    }

@router.post("/storage/google-drive/accounts")
async def add_google_drive_account(
    credentials: AccountCredentials,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Add a new Google Drive account"""
    
    # Validate service account key JSON
    try:
        key_data = json.loads(credentials.service_account_key)
        if not all(key in key_data for key in ["type", "project_id", "private_key_id", "private_key", "client_email"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid service account key format"
            )
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON format for service account key"
        )
    
    # Mock account creation
    new_account_id = f"account_{len(await list_google_drive_accounts(request, current_admin)) + 1}"
    
    # In production, this would:
    # 1. Validate the credentials against Google Drive API
    # 2. Test account access and permissions
    # 3. Store encrypted credentials securely
    # 4. Add to the pool manager
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="add_gdrive_account",
        details=f"Added new Google Drive account: {credentials.account_alias} ({credentials.account_email})",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/storage/google-drive/accounts"
    )
    
    return {
        "message": "Google Drive account added successfully",
        "account_id": new_account_id,
        "account_email": credentials.account_email,
        "account_alias": credentials.account_alias
    }

@router.delete("/storage/google-drive/accounts/{account_id}")
async def remove_google_drive_account(
    account_id: str,
    request: Request,
    force: bool = Query(False, description="Force removal even if account has files"),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Remove a Google Drive account"""
    
    # Check if account has files (mock check)
    files_count = 150  # Mock file count
    
    if files_count > 0 and not force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Account has {files_count} files. Use force=true to remove anyway, or migrate files first."
        )
    
    # Mock removal logic
    # In production, this would:
    # 1. Check if account has files
    # 2. Optionally migrate files to other accounts
    # 3. Remove from pool manager
    # 4. Securely delete stored credentials
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="remove_gdrive_account",
        details=f"Removed Google Drive account: {account_id} (force={force})",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/storage/google-drive/accounts/{account_id}"
    )
    
    return {
        "message": f"Google Drive account {account_id} removed successfully",
        "files_affected": files_count if force else 0
    }

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
        "last_updated": datetime.utcnow() - timedelta(days=2),
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
        "updated_at": datetime.utcnow(),
        "updated_by": current_admin.email
    }

@router.post("/storage/google-drive/accounts/{account_id}/health-check")
async def perform_health_check(
    account_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Perform manual health check on a Google Drive account"""
    
    # Mock health check results
    health_check_result = {
        "account_id": account_id,
        "check_timestamp": datetime.utcnow(),
        "overall_status": "healthy",
        "checks": {
            "api_connectivity": {
                "status": "pass",
                "response_time_ms": 145,
                "details": "Successfully connected to Google Drive API"
            },
            "authentication": {
                "status": "pass",
                "details": "Service account authentication successful"
            },
            "permissions": {
                "status": "pass",
                "details": "All required permissions available"
            },
            "quota_status": {
                "status": "pass",
                "usage_percentage": 3.0,
                "details": "Storage usage within normal limits"
            },
            "performance": {
                "status": "warning",
                "upload_success_rate": 94.2,
                "details": "Success rate slightly below optimal (96%+)"
            }
        },
        "recommendations": [
            "Monitor upload success rate closely",
            "Consider account optimization if performance degrades further"
        ]
    }
    
    # Determine overall status
    statuses = [check["status"] for check in health_check_result["checks"].values()]
    if "fail" in statuses:
        health_check_result["overall_status"] = "unhealthy"
    elif "warning" in statuses:
        health_check_result["overall_status"] = "warning"
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="gdrive_health_check",
        details=f"Performed health check on account {account_id}: {health_check_result['overall_status']}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/storage/google-drive/accounts/{account_id}/health-check"
    )
    
    return health_check_result

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