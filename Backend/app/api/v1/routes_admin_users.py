from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import Optional, List
from datetime import datetime
from app.services.admin_auth_service import get_current_admin, log_admin_activity, get_client_ip
from app.services.auth_service import get_password_hash
from app.models.admin import AdminUserInDB
from app.models.user import UserInDB, UserRole
from app.db.mongodb import db
from pydantic import BaseModel, EmailStr
import re

router = APIRouter()

# Pydantic models for user management
class UserListResponse(BaseModel):
    users: List[dict]
    total: int
    page: int
    limit: int
    total_pages: int

class UserDetailResponse(BaseModel):
    user: dict
    files_count: int
    storage_used: int
    last_activity: Optional[datetime]

class UserUpdateRequest(BaseModel):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    storage_quota: Optional[int] = None  # in bytes

class UserStatusUpdateRequest(BaseModel):
    action: str  # 'ban', 'suspend', 'activate'
    reason: Optional[str] = None

class UserPasswordResetRequest(BaseModel):
    new_password: str

class BulkUserActionRequest(BaseModel):
    user_emails: List[str]
    action: str  # 'ban', 'suspend', 'activate', 'delete'
    reason: Optional[str] = None

@router.get("/users", response_model=UserListResponse)
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None),  # 'active', 'suspended', 'banned'
    sort_by: Optional[str] = Query("created_at"),
    sort_order: Optional[str] = Query("desc"),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """List users with pagination, search, and filters"""
    
    # Build query
    query = {}
    
    # Search filter
    if search:
        query["$or"] = [
            {"email": {"$regex": re.escape(search), "$options": "i"}},
            {"_id": {"$regex": re.escape(search), "$options": "i"}}
        ]
    
    # Role filter
    if role and role in ["regular", "admin", "superadmin"]:
        query["role"] = role
    
    # Status filter
    if status:
        if status == "active":
            query["$or"] = [
                {"is_suspended": {"$ne": True}},
                {"is_banned": {"$ne": True}},
                {"is_suspended": {"$exists": False}},
                {"is_banned": {"$exists": False}}
            ]
        elif status == "suspended":
            query["is_suspended"] = True
        elif status == "banned":
            query["is_banned"] = True
    
    # Get total count
    total = db.users.count_documents(query)
    
    # Calculate pagination
    skip = (page - 1) * limit
    total_pages = (total + limit - 1) // limit
    
    # Build sort
    sort_direction = 1 if sort_order == "asc" else -1
    sort_field = sort_by if sort_by in ["email", "role", "created_at", "last_login"] else "created_at"
    
    # Get users
    users_cursor = db.users.find(
        query,
        {"hashed_password": 0}  # Exclude password hash
    ).sort(sort_field, sort_direction).skip(skip).limit(limit)
    
    users = list(users_cursor)
    
    # Add computed fields
    for user in users:
        # Get user file statistics
        files_count = db.files.count_documents({"uploader_email": user["email"]}) if "files" in db.list_collection_names() else 0
        user["files_count"] = files_count
        
        # Calculate storage used (mock for now)
        user["storage_used"] = files_count * 1024 * 1024  # Mock: 1MB per file
        
        # Add status
        user["status"] = "banned" if user.get("is_banned") else "suspended" if user.get("is_suspended") else "active"
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="list_users",
        details=f"Listed users with search='{search}', role='{role}', status='{status}'",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/users"
    )
    
    return UserListResponse(
        users=users,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages
    )

@router.get("/users/{user_email}", response_model=UserDetailResponse)
async def get_user_detail(
    user_email: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get detailed user information"""
    
    user = db.users.find_one({"email": user_email}, {"hashed_password": 0})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Get user statistics
    files_count = db.files.count_documents({"uploader_email": user_email}) if "files" in db.list_collection_names() else 0
    storage_used = files_count * 1024 * 1024  # Mock calculation
    
    # Get last activity (mock for now)
    last_activity = user.get("last_login")
    
    # Add computed fields
    user["files_count"] = files_count
    user["storage_used"] = storage_used
    user["status"] = "banned" if user.get("is_banned") else "suspended" if user.get("is_suspended") else "active"
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_user_detail",
        details=f"Viewed user details for: {user_email}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/users/{user_email}"
    )
    
    return UserDetailResponse(
        user=user,
        files_count=files_count,
        storage_used=storage_used,
        last_activity=last_activity
    )

@router.put("/users/{user_email}")
async def update_user(
    user_email: str,
    update_data: UserUpdateRequest,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Update user information"""
    
    user = db.users.find_one({"email": user_email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Build update document
    update_doc = {}
    changes = []
    
    if update_data.role is not None:
        update_doc["role"] = update_data.role.value
        update_doc["is_admin"] = update_data.role in [UserRole.ADMIN, UserRole.SUPERADMIN]
        changes.append(f"role to {update_data.role.value}")
    
    if update_data.is_active is not None:
        if update_data.is_active:
            update_doc["is_suspended"] = False
            update_doc["is_banned"] = False
            changes.append("activated user")
        else:
            update_doc["is_suspended"] = True
            changes.append("suspended user")
    
    if update_data.storage_quota is not None:
        update_doc["storage_quota"] = update_data.storage_quota
        changes.append(f"storage quota to {update_data.storage_quota} bytes")
    
    if update_doc:
        update_doc["updated_at"] = datetime.utcnow()
        db.users.update_one({"email": user_email}, {"$set": update_doc})
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="update_user",
        details=f"Updated user {user_email}: {', '.join(changes)}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/users/{user_email}"
    )
    
    return {"message": "User updated successfully", "changes": changes}

@router.post("/users/{user_email}/status")
async def update_user_status(
    user_email: str,
    status_data: UserStatusUpdateRequest,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Ban, suspend, or activate user"""
    
    user = db.users.find_one({"email": user_email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent admins from banning themselves
    if user_email == current_admin.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own status"
        )
    
    update_doc = {"updated_at": datetime.utcnow()}
    action_msg = ""
    
    if status_data.action == "ban":
        update_doc["is_banned"] = True
        update_doc["is_suspended"] = False
        update_doc["banned_at"] = datetime.utcnow()
        update_doc["ban_reason"] = status_data.reason
        action_msg = "banned"
    elif status_data.action == "suspend":
        update_doc["is_suspended"] = True
        update_doc["is_banned"] = False
        update_doc["suspended_at"] = datetime.utcnow()
        update_doc["suspension_reason"] = status_data.reason
        action_msg = "suspended"
    elif status_data.action == "activate":
        update_doc["is_banned"] = False
        update_doc["is_suspended"] = False
        update_doc["activated_at"] = datetime.utcnow()
        action_msg = "activated"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid action. Use 'ban', 'suspend', or 'activate'"
        )
    
    db.users.update_one({"email": user_email}, {"$set": update_doc})
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action=f"user_{status_data.action}",
        details=f"User {action_msg}: {user_email}. Reason: {status_data.reason or 'No reason provided'}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/users/{user_email}/status"
    )
    
    return {"message": f"User {action_msg} successfully"}

@router.post("/users/{user_email}/reset-password")
async def reset_user_password(
    user_email: str,
    password_data: UserPasswordResetRequest,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Reset user password"""
    
    user = db.users.find_one({"email": user_email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Hash new password
    hashed_password = get_password_hash(password_data.new_password)
    
    # Update password
    db.users.update_one(
        {"email": user_email},
        {
            "$set": {
                "hashed_password": hashed_password,
                "password_reset_at": datetime.utcnow(),
                "password_reset_by": current_admin.email
            }
        }
    )
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="reset_user_password",
        details=f"Reset password for user: {user_email}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/users/{user_email}/reset-password"
    )
    
    return {"message": "Password reset successfully"}

@router.post("/users/bulk-action")
async def bulk_user_action(
    action_data: BulkUserActionRequest,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Perform bulk actions on multiple users"""
    
    if len(action_data.user_emails) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot perform bulk action on more than 100 users at once"
        )
    
    # Prevent admin from including themselves in ban/suspend actions
    if action_data.action in ["ban", "suspend", "delete"] and current_admin.email in action_data.user_emails:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot perform this action on your own account"
        )
    
    update_doc = {"updated_at": datetime.utcnow()}
    action_msg = ""
    
    if action_data.action == "ban":
        update_doc["is_banned"] = True
        update_doc["is_suspended"] = False
        update_doc["banned_at"] = datetime.utcnow()
        update_doc["ban_reason"] = action_data.reason
        action_msg = "banned"
    elif action_data.action == "suspend":
        update_doc["is_suspended"] = True
        update_doc["is_banned"] = False
        update_doc["suspended_at"] = datetime.utcnow()
        update_doc["suspension_reason"] = action_data.reason
        action_msg = "suspended"
    elif action_data.action == "activate":
        update_doc["is_banned"] = False
        update_doc["is_suspended"] = False
        update_doc["activated_at"] = datetime.utcnow()
        action_msg = "activated"
    elif action_data.action == "delete":
        # Soft delete - mark as deleted instead of actually deleting
        update_doc["is_deleted"] = True
        update_doc["deleted_at"] = datetime.utcnow()
        update_doc["deleted_by"] = current_admin.email
        action_msg = "deleted"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid action. Use 'ban', 'suspend', 'activate', or 'delete'"
        )
    
    # Perform bulk update
    result = db.users.update_many(
        {"email": {"$in": action_data.user_emails}},
        {"$set": update_doc}
    )
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action=f"bulk_user_{action_data.action}",
        details=f"Bulk {action_msg} {result.modified_count} users: {', '.join(action_data.user_emails[:10])}{'...' if len(action_data.user_emails) > 10 else ''}. Reason: {action_data.reason or 'No reason provided'}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/users/bulk-action"
    )
    
    return {
        "message": f"{result.modified_count} users {action_msg} successfully",
        "affected_count": result.modified_count
    }

@router.get("/users/{user_email}/activity")
async def get_user_activity(
    user_email: str,
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get user activity timeline"""
    
    user = db.users.find_one({"email": user_email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Mock activity data - replace with actual activity tracking
    activities = [
        {
            "timestamp": datetime.utcnow(),
            "action": "login",
            "details": "User logged in",
            "ip_address": "192.168.1.1"
        },
        {
            "timestamp": datetime.utcnow(),
            "action": "upload_file",
            "details": "Uploaded document.pdf",
            "ip_address": "192.168.1.1"
        }
    ]
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_user_activity",
        details=f"Viewed activity for user: {user_email}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/users/{user_email}/activity"
    )
    
    return {"activities": activities}

@router.get("/users/export")
async def export_users(
    request: Request,
    format: str = Query("csv", pattern="^(csv|json)$"),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Export user data"""
    
    users = list(db.users.find({}, {"hashed_password": 0}))
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="export_users",
        details=f"Exported {len(users)} users in {format} format",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/users/export"
    )
    
    if format == "json":
        return {"users": users, "exported_at": datetime.utcnow(), "total": len(users)}
    else:
        # For CSV, we'll return the data and let frontend handle CSV generation
        return {"users": users, "format": "csv", "exported_at": datetime.utcnow()}


# USER ANALYTICS ENDPOINTS

# Response models for analytics
class UserRegistrationTrends(BaseModel):
    period: str  # 'daily', 'weekly', 'monthly'
    data: List[dict]  # [{date: str, count: int}]
    total_registrations: int
    growth_rate: float

class ActiveUsersStats(BaseModel):
    daily_active: int
    weekly_active: int 
    monthly_active: int
    total_active: int

class UserGeographicData(BaseModel):
    countries: List[dict]  # [{country: str, count: int, percentage: float}]
    total_countries: int

class StorageUsageAnalytics(BaseModel):
    total_storage: int
    average_per_user: float
    top_users: List[dict]  # [{email: str, storage_used: int, files_count: int}]
    storage_distribution: List[dict]  # [{range: str, count: int}]

class UserActivityPatterns(BaseModel):
    upload_patterns: List[dict]  # [{hour: int, uploads: int}]
    download_patterns: List[dict]  # [{hour: int, downloads: int}]
    most_active_users: List[dict]

class UserRetentionMetrics(BaseModel):
    retention_rate_7d: float
    retention_rate_30d: float  
    churn_rate: float
    new_users_last_30d: int


@router.get("/analytics/registration-trends", response_model=UserRegistrationTrends)
async def get_registration_trends(
    request: Request,
    period: str = Query("monthly", pattern="^(daily|weekly|monthly)$"),
    days: int = Query(30, ge=7, le=365),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get user registration trends over time"""
    
    from datetime import timedelta
    import calendar
    
    # Calculate date range
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    # Build aggregation pipeline based on period
    if period == "daily":
        group_format = "%Y-%m-%d"
        date_format = "$dateToString"
    elif period == "weekly":
        group_format = "%Y-W%V"  # Year-Week format
        date_format = "$dateToString" 
    else:  # monthly
        group_format = "%Y-%m"
        date_format = "$dateToString"
    
    pipeline = [
        {
            "$match": {
                "created_at": {
                    "$gte": start_date,
                    "$lte": end_date
                }
            }
        },
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": group_format,
                        "date": "$created_at"
                    }
                },
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"_id": 1}}
    ]
    
    # Execute aggregation
    results = list(db.users.aggregate(pipeline))
    
    # Format results
    data = [{"date": result["_id"], "count": result["count"]} for result in results]
    total_registrations = sum(item["count"] for item in data)
    
    # Calculate growth rate
    if len(data) >= 2:
        recent_period = sum(item["count"] for item in data[-7:])  # Last week
        previous_period = sum(item["count"] for item in data[-14:-7]) if len(data) >= 14 else 0
        growth_rate = ((recent_period - previous_period) / max(previous_period, 1)) * 100
    else:
        growth_rate = 0.0
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_registration_trends",
        details=f"Viewed {period} registration trends for {days} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/analytics/registration-trends"
    )
    
    return UserRegistrationTrends(
        period=period,
        data=data,
        total_registrations=total_registrations,
        growth_rate=round(growth_rate, 2)
    )


@router.get("/analytics/active-users", response_model=ActiveUsersStats)
async def get_active_users_stats(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get active users statistics"""
    
    from datetime import timedelta
    
    now = datetime.utcnow()
    
    # Define time periods
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    
    # Count active users for different periods
    daily_active = db.users.count_documents({
        "last_login": {"$gte": day_ago},
        "$or": [
            {"is_suspended": {"$ne": True}},
            {"is_banned": {"$ne": True}},
            {"is_suspended": {"$exists": False}},
            {"is_banned": {"$exists": False}}
        ]
    })
    
    weekly_active = db.users.count_documents({
        "last_login": {"$gte": week_ago},
        "$or": [
            {"is_suspended": {"$ne": True}},
            {"is_banned": {"$ne": True}},
            {"is_suspended": {"$exists": False}},
            {"is_banned": {"$exists": False}}
        ]
    })
    
    monthly_active = db.users.count_documents({
        "last_login": {"$gte": month_ago},
        "$or": [
            {"is_suspended": {"$ne": True}},
            {"is_banned": {"$ne": True}},
            {"is_suspended": {"$exists": False}},
            {"is_banned": {"$exists": False}}
        ]
    })
    
    total_active = db.users.count_documents({
        "$or": [
            {"is_suspended": {"$ne": True}},
            {"is_banned": {"$ne": True}},
            {"is_suspended": {"$exists": False}},
            {"is_banned": {"$exists": False}}
        ]
    })
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_active_users",
        details="Viewed active users statistics",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/analytics/active-users"
    )
    
    return ActiveUsersStats(
        daily_active=daily_active,
        weekly_active=weekly_active,
        monthly_active=monthly_active,
        total_active=total_active
    )


@router.get("/analytics/geographic-distribution", response_model=UserGeographicData)
async def get_geographic_distribution(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get user geographic distribution based on registration IP or location data"""
    
    # For now, we'll use mock data as IP geolocation requires external services
    # In production, you would integrate with a service like MaxMind GeoIP
    
    mock_countries = [
        {"country": "United States", "count": 45, "percentage": 35.2},
        {"country": "United Kingdom", "count": 23, "percentage": 18.0},
        {"country": "Germany", "count": 18, "percentage": 14.1},
        {"country": "France", "count": 15, "percentage": 11.7},
        {"country": "Canada", "count": 12, "percentage": 9.4},
        {"country": "Australia", "count": 8, "percentage": 6.3},
        {"country": "Others", "count": 7, "percentage": 5.3}
    ]
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_geographic_distribution",
        details="Viewed user geographic distribution",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/analytics/geographic-distribution"
    )
    
    return UserGeographicData(
        countries=mock_countries,
        total_countries=len(mock_countries)
    )


@router.get("/analytics/storage-usage", response_model=StorageUsageAnalytics)
async def get_storage_usage_analytics(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get storage usage analytics"""
    
    try:
        # Check if files collection exists
        collections = db.list_collection_names()
        
        if "files" in collections:
            # Get users with their file counts and storage usage
            pipeline = [
                {
                    "$lookup": {
                        "from": "files",
                        "localField": "email",
                        "foreignField": "uploader_email",
                        "as": "user_files"
                    }
                },
                {
                    "$addFields": {
                        "files_count": {"$size": "$user_files"},
                        "storage_used": {
                            "$multiply": [{"$size": "$user_files"}, 1024 * 1024]  # Mock: 1MB per file
                        }
                    }
                },
                {
                    "$project": {
                        "email": 1,
                        "files_count": 1,
                        "storage_used": 1,
                        "hashed_password": 0
                    }
                }
            ]
            
            users_with_storage = list(db.users.aggregate(pipeline))
        else:
            # Mock data when files collection doesn't exist
            users = list(db.users.find({}, {"email": 1, "hashed_password": 0}))
            users_with_storage = []
            for user in users:
                # Mock file count and storage
                mock_files = abs(hash(user["email"])) % 50  # 0-49 files per user
                users_with_storage.append({
                    "email": user["email"],
                    "files_count": mock_files,
                    "storage_used": mock_files * 1024 * 1024  # 1MB per file
                })
    except Exception as e:
        # Fallback to simple mock data if anything fails
        users_with_storage = [
            {"email": "test1@example.com", "files_count": 25, "storage_used": 26214400},
            {"email": "test2@example.com", "files_count": 15, "storage_used": 15728640},
            {"email": "test3@example.com", "files_count": 35, "storage_used": 36700160},
            {"email": "admin@directdrive.com", "files_count": 5, "storage_used": 5242880}
        ]
    
    # Calculate total storage and average
    total_storage = sum(user.get("storage_used", 0) for user in users_with_storage)
    total_users = len(users_with_storage)
    average_per_user = total_storage / max(total_users, 1)
    
    # Get top users by storage
    top_users = sorted(
        users_with_storage, 
        key=lambda x: x.get("storage_used", 0), 
        reverse=True
    )[:10]
    
    # Create storage distribution ranges
    ranges = [
        {"range": "0-100MB", "count": 0},
        {"range": "100MB-1GB", "count": 0},
        {"range": "1GB-10GB", "count": 0},
        {"range": "10GB+", "count": 0}
    ]
    
    for user in users_with_storage:
        storage_mb = user.get("storage_used", 0) / (1024 * 1024)
        if storage_mb <= 100:
            ranges[0]["count"] += 1
        elif storage_mb <= 1024:
            ranges[1]["count"] += 1
        elif storage_mb <= 10240:
            ranges[2]["count"] += 1
        else:
            ranges[3]["count"] += 1
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_storage_analytics",
        details="Viewed storage usage analytics",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/analytics/storage-usage"
    )
    
    return StorageUsageAnalytics(
        total_storage=total_storage,
        average_per_user=round(average_per_user, 2),
        top_users=top_users,
        storage_distribution=ranges
    )


@router.get("/analytics/user-activity-patterns", response_model=UserActivityPatterns)
async def get_user_activity_patterns(
    request: Request,
    days: int = Query(7, ge=1, le=30),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get user activity patterns (upload/download by hour)"""
    
    # Mock data for activity patterns
    # In production, you would query actual upload/download logs
    
    upload_patterns = []
    download_patterns = []
    
    for hour in range(24):
        # Generate mock data with realistic patterns (higher during business hours)
        base_uploads = 10
        base_downloads = 15
        
        # Peak hours (9 AM - 5 PM)
        if 9 <= hour <= 17:
            upload_multiplier = 3
            download_multiplier = 2.5
        # Evening hours
        elif 18 <= hour <= 22:
            upload_multiplier = 1.5
            download_multiplier = 2
        # Night hours
        else:
            upload_multiplier = 0.3
            download_multiplier = 0.5
            
        uploads = int(base_uploads * upload_multiplier + (hash(hour) % 5))
        downloads = int(base_downloads * download_multiplier + (hash(hour + 1) % 8))
        
        upload_patterns.append({"hour": hour, "uploads": uploads})
        download_patterns.append({"hour": hour, "downloads": downloads})
    
    # Get most active users
    most_active_users = list(db.users.find(
        {"last_login": {"$exists": True}},
        {"email": 1, "last_login": 1, "_id": 0}
    ).sort("last_login", -1).limit(10))
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_activity_patterns",
        details=f"Viewed user activity patterns for {days} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/analytics/user-activity-patterns"
    )
    
    return UserActivityPatterns(
        upload_patterns=upload_patterns,
        download_patterns=download_patterns,
        most_active_users=most_active_users
    )


@router.get("/analytics/user-retention", response_model=UserRetentionMetrics)
async def get_user_retention_metrics(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get user retention metrics"""
    
    from datetime import timedelta
    
    now = datetime.utcnow()
    
    # Users registered 7 days ago
    seven_days_ago = now - timedelta(days=7)
    users_registered_7d_ago = db.users.count_documents({
        "created_at": {
            "$gte": seven_days_ago - timedelta(days=1),
            "$lt": seven_days_ago + timedelta(days=1)
        }
    })
    
    # Of those, how many are still active?
    retained_7d = db.users.count_documents({
        "created_at": {
            "$gte": seven_days_ago - timedelta(days=1),
            "$lt": seven_days_ago + timedelta(days=1)
        },
        "last_login": {"$gte": seven_days_ago}
    })
    
    # Users registered 30 days ago
    thirty_days_ago = now - timedelta(days=30)
    users_registered_30d_ago = db.users.count_documents({
        "created_at": {
            "$gte": thirty_days_ago - timedelta(days=1),
            "$lt": thirty_days_ago + timedelta(days=1)
        }
    })
    
    # Of those, how many are still active?
    retained_30d = db.users.count_documents({
        "created_at": {
            "$gte": thirty_days_ago - timedelta(days=1),
            "$lt": thirty_days_ago + timedelta(days=1)
        },
        "last_login": {"$gte": thirty_days_ago}
    })
    
    # Calculate retention rates
    retention_rate_7d = (retained_7d / max(users_registered_7d_ago, 1)) * 100
    retention_rate_30d = (retained_30d / max(users_registered_30d_ago, 1)) * 100
    
    # Churn rate (users who haven't logged in for 30+ days)
    total_users = db.users.count_documents({})
    inactive_users = db.users.count_documents({
        "$or": [
            {"last_login": {"$lt": thirty_days_ago}},
            {"last_login": {"$exists": False}}
        ]
    })
    churn_rate = (inactive_users / max(total_users, 1)) * 100
    
    # New users in last 30 days
    new_users_30d = db.users.count_documents({
        "created_at": {"$gte": thirty_days_ago}
    })
    
    # Log admin activity
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_retention_metrics",
        details="Viewed user retention metrics",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/analytics/user-retention"
    )
    
    return UserRetentionMetrics(
        retention_rate_7d=round(retention_rate_7d, 2),
        retention_rate_30d=round(retention_rate_30d, 2),
        churn_rate=round(churn_rate, 2),
        new_users_last_30d=new_users_30d
    )