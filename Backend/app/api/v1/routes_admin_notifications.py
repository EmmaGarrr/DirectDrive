from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from bson import ObjectId
from app.models.admin import AdminUserInDB
from app.db.mongodb import db
from app.services.admin_auth_service import get_current_admin, get_current_superadmin, log_admin_activity, get_client_ip
import asyncio
import uuid
from enum import Enum

router = APIRouter()

# ================================
# NOTIFICATION MODELS
# ================================

class NotificationType(str, Enum):
    SYSTEM = "system"
    EMAIL = "email"
    IN_APP = "in_app"
    SCHEDULED = "scheduled"

class NotificationPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"

class NotificationStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TargetType(str, Enum):
    ALL_USERS = "all_users"
    ACTIVE_USERS = "active_users"
    INACTIVE_USERS = "inactive_users"
    SPECIFIC_USERS = "specific_users"
    USER_ROLE = "user_role"

class NotificationTemplate(BaseModel):
    template_id: str = Field(..., max_length=100)
    name: str = Field(..., max_length=200)
    subject: str = Field(..., max_length=300)
    content: str = Field(..., max_length=5000)
    notification_type: NotificationType
    priority: NotificationPriority = NotificationPriority.MEDIUM
    is_active: bool = True

class NotificationCreate(BaseModel):
    title: str = Field(..., max_length=300)
    message: str = Field(..., max_length=5000)
    notification_type: NotificationType
    priority: NotificationPriority = NotificationPriority.MEDIUM
    target_type: TargetType
    target_users: Optional[List[str]] = None  # List of user emails or IDs
    schedule_time: Optional[datetime] = None
    template_id: Optional[str] = None
    email_subject: Optional[str] = Field(None, max_length=300)
    expires_at: Optional[datetime] = None

class NotificationUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=300)
    message: Optional[str] = Field(None, max_length=5000)
    priority: Optional[NotificationPriority] = None
    schedule_time: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    status: Optional[NotificationStatus] = None

class UserGroupFilter(BaseModel):
    registration_date_from: Optional[datetime] = None
    registration_date_to: Optional[datetime] = None
    last_active_from: Optional[datetime] = None
    last_active_to: Optional[datetime] = None
    storage_usage_min: Optional[int] = None  # in MB
    storage_usage_max: Optional[int] = None  # in MB
    include_active: bool = True
    include_inactive: bool = False

# ================================
# NOTIFICATION MANAGEMENT ENDPOINTS
# ================================

@router.get("/notifications")
async def get_notifications(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status_filter: Optional[NotificationStatus] = Query(None),
    type_filter: Optional[NotificationType] = Query(None),
    priority_filter: Optional[NotificationPriority] = Query(None),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get all notifications with filtering and pagination"""
    # db is imported directly
    
    # Build filter query
    filter_query = {}
    if status_filter:
        filter_query["status"] = status_filter.value
    if type_filter:
        filter_query["notification_type"] = type_filter.value
    if priority_filter:
        filter_query["priority"] = priority_filter.value
    
    # Count total notifications
    total = db.notifications.count_documents(filter_query)
    
    # Get notifications with pagination
    notifications = list(
        db.notifications.find(filter_query)
        .sort("created_at", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    
    # Convert ObjectId to string
    for notification in notifications:
        notification["_id"] = str(notification["_id"])
    
    # Get statistics
    stats = {
        "total_notifications": total,
        "status_breakdown": {},
        "type_breakdown": {},
        "priority_breakdown": {}
    }
    
    # Get status breakdown
    status_pipeline = [
        {"$match": filter_query},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    for item in db.notifications.aggregate(status_pipeline):
        stats["status_breakdown"][item["_id"]] = item["count"]
    
    # Get type breakdown
    type_pipeline = [
        {"$match": filter_query},
        {"$group": {"_id": "$notification_type", "count": {"$sum": 1}}}
    ]
    for item in db.notifications.aggregate(type_pipeline):
        stats["type_breakdown"][item["_id"]] = item["count"]
    
    # Get priority breakdown
    priority_pipeline = [
        {"$match": filter_query},
        {"$group": {"_id": "$priority", "count": {"$sum": 1}}}
    ]
    for item in db.notifications.aggregate(priority_pipeline):
        stats["priority_breakdown"][item["_id"]] = item["count"]
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_notifications",
        details=f"Viewed notifications list (page {page}, {len(notifications)} items)",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/notifications"
    )
    
    return {
        "notifications": notifications,
        "total": total,
        "page": page,
        "limit": limit,
        "statistics": stats
    }

@router.post("/notifications")
async def create_notification(
    notification_data: NotificationCreate,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Create a new notification"""
    # db is imported directly
    
    # Validate target users if specific users are targeted
    if notification_data.target_type == TargetType.SPECIFIC_USERS:
        if not notification_data.target_users or len(notification_data.target_users) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target users must be specified for specific user targeting"
            )
    
    # Generate notification ID
    notification_id = str(uuid.uuid4())
    
    # Determine initial status
    initial_status = NotificationStatus.DRAFT
    if notification_data.schedule_time:
        if notification_data.schedule_time > datetime.utcnow():
            initial_status = NotificationStatus.SCHEDULED
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Schedule time must be in the future"
            )
    
    # Create notification document
    notification_doc = {
        "_id": notification_id,
        "title": notification_data.title,
        "message": notification_data.message,
        "notification_type": notification_data.notification_type.value,
        "priority": notification_data.priority.value,
        "target_type": notification_data.target_type.value,
        "target_users": notification_data.target_users or [],
        "schedule_time": notification_data.schedule_time,
        "email_subject": notification_data.email_subject,
        "expires_at": notification_data.expires_at,
        "template_id": notification_data.template_id,
        "status": initial_status.value,
        "created_by": current_admin.email,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "sent_at": None,
        "delivery_stats": {
            "total_recipients": 0,
            "successful_deliveries": 0,
            "failed_deliveries": 0,
            "pending_deliveries": 0
        }
    }
    
    # Insert notification
    result = db.notifications.insert_one(notification_doc)
    
    # If it's an immediate notification, trigger delivery
    if initial_status == NotificationStatus.DRAFT and not notification_data.schedule_time:
        # Start delivery process in background
        asyncio.create_task(deliver_notification(notification_id))
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="create_notification",
        details=f"Created notification: {notification_data.title} (Type: {notification_data.notification_type.value}, Priority: {notification_data.priority.value})",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/notifications"
    )
    
    return {
        "message": "Notification created successfully",
        "notification_id": notification_id,
        "status": initial_status.value
    }

@router.get("/notifications/{notification_id}")
async def get_notification_details(
    notification_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get detailed information about a specific notification"""
    # db is imported directly
    
    notification = db.notifications.find_one({"_id": notification_id})
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    # Convert ObjectId to string
    notification["_id"] = str(notification["_id"])
    
    # Get delivery logs for this notification
    delivery_logs = list(
        db.notification_deliveries.find({"notification_id": notification_id})
        .sort("attempted_at", -1)
        .limit(100)
    )
    
    for log in delivery_logs:
        log["_id"] = str(log["_id"])
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_notification_details",
        details=f"Viewed notification details: {notification.get('title', 'Unknown')}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/notifications/{notification_id}"
    )
    
    return {
        "notification": notification,
        "delivery_logs": delivery_logs
    }

@router.put("/notifications/{notification_id}")
async def update_notification(
    notification_id: str,
    update_data: NotificationUpdate,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Update a notification (only if not sent)"""
    # db is imported directly
    
    notification = db.notifications.find_one({"_id": notification_id})
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    # Check if notification can be updated
    if notification["status"] in [NotificationStatus.SENT.value, NotificationStatus.FAILED.value]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot update notification that has already been sent or failed"
        )
    
    # Build update document
    update_doc = {"updated_at": datetime.utcnow()}
    
    if update_data.title is not None:
        update_doc["title"] = update_data.title
    if update_data.message is not None:
        update_doc["message"] = update_data.message
    if update_data.priority is not None:
        update_doc["priority"] = update_data.priority.value
    if update_data.schedule_time is not None:
        if update_data.schedule_time > datetime.utcnow():
            update_doc["schedule_time"] = update_data.schedule_time
            update_doc["status"] = NotificationStatus.SCHEDULED.value
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Schedule time must be in the future"
            )
    if update_data.expires_at is not None:
        update_doc["expires_at"] = update_data.expires_at
    if update_data.status is not None:
        update_doc["status"] = update_data.status.value
    
    # Update notification
    db.notifications.update_one(
        {"_id": notification_id},
        {"$set": update_doc}
    )
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="update_notification",
        details=f"Updated notification: {notification.get('title', 'Unknown')}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/notifications/{notification_id}"
    )
    
    return {"message": "Notification updated successfully"}

@router.delete("/notifications/{notification_id}")
async def delete_notification(
    notification_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_superadmin)  # Superadmin only
):
    """Delete a notification (superadmin only)"""
    # db is imported directly
    
    notification = db.notifications.find_one({"_id": notification_id})
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    # Delete notification and related delivery logs
    db.notifications.delete_one({"_id": notification_id})
    db.notification_deliveries.delete_many({"notification_id": notification_id})
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="delete_notification",
        details=f"Deleted notification: {notification.get('title', 'Unknown')}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/notifications/{notification_id}"
    )
    
    return {"message": "Notification deleted successfully"}

@router.post("/notifications/{notification_id}/send")
async def send_notification_now(
    notification_id: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Send a notification immediately"""
    # db is imported directly
    
    notification = db.notifications.find_one({"_id": notification_id})
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    # Check if notification can be sent
    if notification["status"] == NotificationStatus.SENT.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notification has already been sent"
        )
    
    # Update status and trigger delivery
    db.notifications.update_one(
        {"_id": notification_id},
        {
            "$set": {
                "status": NotificationStatus.SENT.value,
                "sent_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
        }
    )
    
    # Start delivery process in background
    asyncio.create_task(deliver_notification(notification_id))
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="send_notification",
        details=f"Manually sent notification: {notification.get('title', 'Unknown')}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/notifications/{notification_id}/send"
    )
    
    return {"message": "Notification sent successfully"}

# ================================
# NOTIFICATION TEMPLATES ENDPOINTS
# ================================

@router.get("/notification-templates")
async def get_notification_templates(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get all notification templates"""
    # db is imported directly
    
    templates = list(db.notification_templates.find({"is_active": True}))
    
    for template in templates:
        template["_id"] = str(template["_id"])
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_notification_templates",
        details=f"Viewed notification templates ({len(templates)} templates)",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/notification-templates"
    )
    
    return {"templates": templates}

@router.post("/notification-templates")
async def create_notification_template(
    template_data: NotificationTemplate,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Create a new notification template"""
    # db is imported directly
    
    # Check if template ID already exists
    existing = db.notification_templates.find_one({"template_id": template_data.template_id})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template ID already exists"
        )
    
    # Create template document
    template_doc = {
        "_id": str(uuid.uuid4()),
        "template_id": template_data.template_id,
        "name": template_data.name,
        "subject": template_data.subject,
        "content": template_data.content,
        "notification_type": template_data.notification_type.value,
        "priority": template_data.priority.value,
        "is_active": template_data.is_active,
        "created_by": current_admin.email,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "usage_count": 0
    }
    
    db.notification_templates.insert_one(template_doc)
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="create_notification_template",
        details=f"Created notification template: {template_data.name}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/notification-templates"
    )
    
    return {"message": "Notification template created successfully"}

# ================================
# USER TARGETING ENDPOINTS
# ================================

@router.post("/user-groups/preview")
async def preview_user_group(
    filter_data: UserGroupFilter,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Preview users that would be targeted by group filters"""
    # db is imported directly
    
    # Build user filter query
    filter_query = {}
    
    if filter_data.registration_date_from:
        filter_query.setdefault("created_at", {})["$gte"] = filter_data.registration_date_from
    if filter_data.registration_date_to:
        filter_query.setdefault("created_at", {})["$lte"] = filter_data.registration_date_to
    
    if filter_data.last_active_from:
        filter_query.setdefault("last_login", {})["$gte"] = filter_data.last_active_from
    if filter_data.last_active_to:
        filter_query.setdefault("last_login", {})["$lte"] = filter_data.last_active_to
    
    if filter_data.storage_usage_min:
        filter_query.setdefault("storage_used", {})["$gte"] = filter_data.storage_usage_min * 1024 * 1024  # Convert MB to bytes
    if filter_data.storage_usage_max:
        filter_query.setdefault("storage_used", {})["$lte"] = filter_data.storage_usage_max * 1024 * 1024
    
    # Add active/inactive filter
    if filter_data.include_active and not filter_data.include_inactive:
        filter_query["is_active"] = True
    elif filter_data.include_inactive and not filter_data.include_active:
        filter_query["is_active"] = False
    
    # Count matching users
    total_users = db.users.count_documents(filter_query)
    
    # Get sample users (first 10)
    sample_users = list(
        db.users.find(filter_query, {"email": 1, "username": 1, "created_at": 1, "last_login": 1, "is_active": 1})
        .limit(10)
    )
    
    for user in sample_users:
        user["_id"] = str(user["_id"])
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="preview_user_group",
        details=f"Previewed user group filter (matched {total_users} users)",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/user-groups/preview"
    )
    
    return {
        "total_matching_users": total_users,
        "sample_users": sample_users,
        "filter_summary": {
            "registration_date_range": {
                "from": filter_data.registration_date_from,
                "to": filter_data.registration_date_to
            },
            "activity_range": {
                "from": filter_data.last_active_from,
                "to": filter_data.last_active_to
            },
            "storage_range": {
                "min_mb": filter_data.storage_usage_min,
                "max_mb": filter_data.storage_usage_max
            },
            "include_active": filter_data.include_active,
            "include_inactive": filter_data.include_inactive
        }
    }

# ================================
# NOTIFICATION DELIVERY FUNCTIONS
# ================================

async def deliver_notification(notification_id: str):
    """Background task to deliver a notification to targeted users"""
    # db is imported directly
    
    try:
        notification = db.notifications.find_one({"_id": notification_id})
        if not notification:
            return
        
        # Get target users based on targeting criteria
        target_users = []
        
        if notification["target_type"] == TargetType.ALL_USERS.value:
            target_users = list(db.users.find({}, {"email": 1, "username": 1}))
        elif notification["target_type"] == TargetType.ACTIVE_USERS.value:
            target_users = list(db.users.find({"is_active": True}, {"email": 1, "username": 1}))
        elif notification["target_type"] == TargetType.INACTIVE_USERS.value:
            target_users = list(db.users.find({"is_active": False}, {"email": 1, "username": 1}))
        elif notification["target_type"] == TargetType.SPECIFIC_USERS.value:
            target_emails = notification.get("target_users", [])
            target_users = list(db.users.find({"email": {"$in": target_emails}}, {"email": 1, "username": 1}))
        
        # Update delivery stats
        total_recipients = len(target_users)
        successful_deliveries = 0
        failed_deliveries = 0
        
        # Simulate delivery process (in real implementation, this would send emails/push notifications)
        for user in target_users:
            try:
                # Create delivery log entry
                delivery_log = {
                    "_id": str(uuid.uuid4()),
                    "notification_id": notification_id,
                    "user_email": user["email"],
                    "attempted_at": datetime.utcnow(),
                    "delivery_method": notification["notification_type"],
                    "status": "success",
                    "error_message": None
                }
                
                # Simulate delivery (90% success rate)
                import random
                if random.random() < 0.9:
                    successful_deliveries += 1
                    delivery_log["delivered_at"] = datetime.utcnow()
                else:
                    failed_deliveries += 1
                    delivery_log["status"] = "failed"
                    delivery_log["error_message"] = "Simulated delivery failure"
                
                db.notification_deliveries.insert_one(delivery_log)
                
            except Exception as e:
                failed_deliveries += 1
                # Log the failure
                db.notification_deliveries.insert_one({
                    "_id": str(uuid.uuid4()),
                    "notification_id": notification_id,
                    "user_email": user["email"],
                    "attempted_at": datetime.utcnow(),
                    "delivery_method": notification["notification_type"],
                    "status": "failed",
                    "error_message": str(e)
                })
        
        # Update notification with final delivery stats
        db.notifications.update_one(
            {"_id": notification_id},
            {
                "$set": {
                    "delivery_stats": {
                        "total_recipients": total_recipients,
                        "successful_deliveries": successful_deliveries,
                        "failed_deliveries": failed_deliveries,
                        "pending_deliveries": 0
                    },
                    "status": NotificationStatus.SENT.value,
                    "sent_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
    except Exception as e:
        # Mark notification as failed
        db.notifications.update_one(
            {"_id": notification_id},
            {
                "$set": {
                    "status": NotificationStatus.FAILED.value,
                    "updated_at": datetime.utcnow(),
                    "error_message": str(e)
                }
            }
        )

# ================================
# NOTIFICATION STATISTICS
# ================================

@router.get("/notifications/stats/dashboard")
async def get_notification_dashboard_stats(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get notification statistics for dashboard"""
    # db is imported directly
    
    # Date range
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    # Total notifications
    total_notifications = db.notifications.count_documents({})
    
    # Notifications in date range
    recent_notifications = db.notifications.count_documents({
        "created_at": {"$gte": start_date, "$lte": end_date}
    })
    
    # Status breakdown
    status_breakdown = {}
    for status in NotificationStatus:
        count = db.notifications.count_documents({"status": status.value})
        status_breakdown[status.value] = count
    
    # Type breakdown
    type_breakdown = {}
    for ntype in NotificationType:
        count = db.notifications.count_documents({"notification_type": ntype.value})
        type_breakdown[ntype.value] = count
    
    # Delivery statistics
    delivery_stats = db.notifications.aggregate([
        {"$match": {"status": "sent"}},
        {"$group": {
            "_id": None,
            "total_recipients": {"$sum": "$delivery_stats.total_recipients"},
            "successful_deliveries": {"$sum": "$delivery_stats.successful_deliveries"},
            "failed_deliveries": {"$sum": "$delivery_stats.failed_deliveries"}
        }}
    ])
    
    delivery_data = list(delivery_stats)
    if delivery_data:
        delivery_summary = delivery_data[0]
        del delivery_summary["_id"]
        delivery_summary["success_rate"] = (
            delivery_summary["successful_deliveries"] / delivery_summary["total_recipients"] * 100
            if delivery_summary["total_recipients"] > 0 else 0
        )
    else:
        delivery_summary = {
            "total_recipients": 0,
            "successful_deliveries": 0,
            "failed_deliveries": 0,
            "success_rate": 0
        }
    
    # Recent activity (last 7 days)
    recent_activity = []
    for i in range(7):
        day_start = (end_date - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        
        day_count = db.notifications.count_documents({
            "created_at": {"$gte": day_start, "$lt": day_end}
        })
        
        recent_activity.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "count": day_count
        })
    
    recent_activity.reverse()  # Show oldest to newest
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_notification_stats",
        details=f"Viewed notification dashboard statistics ({days} days)",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/notifications/stats/dashboard"
    )
    
    return {
        "summary": {
            "total_notifications": total_notifications,
            "recent_notifications": recent_notifications,
            "active_templates": db.notification_templates.count_documents({"is_active": True}),
            "scheduled_notifications": db.notifications.count_documents({"status": "scheduled"})
        },
        "status_breakdown": status_breakdown,
        "type_breakdown": type_breakdown,
        "delivery_summary": delivery_summary,
        "recent_activity": recent_activity,
        "period_days": days
    }