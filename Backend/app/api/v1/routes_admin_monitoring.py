from fastapi import APIRouter, Depends, Request, Query, HTTPException, status
from datetime import datetime, timedelta
import psutil
import os
import asyncio
import time
import logging
from typing import Dict, Any, List
from app.services.admin_auth_service import get_current_admin, get_current_superadmin, log_admin_activity, get_client_ip
from app.models.admin import AdminUserInDB
from app.db.mongodb import db
from app.core.config import settings
from app.services.background_process_manager import (
    background_process_manager, 
    ProcessType, 
    ProcessPriority, 
    ProcessStatus
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ================================
# SYSTEM HEALTH MONITORING ENDPOINTS
# ================================

@router.get("/monitoring/system-health")
async def get_system_health(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get comprehensive system health metrics"""
    
    try:
        # CPU Usage
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()
        
        # Memory Usage
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        # Disk Usage
        disk_usage = psutil.disk_usage('/')
        
        # Network Stats
        network = psutil.net_io_counters()
        
        # System Info
        boot_time = psutil.boot_time()
        uptime = time.time() - boot_time
        
        # Database Stats (excluding deleted files)
        db_stats = {
            "total_collections": len(db.list_collection_names()),
            "total_files": db.files.count_documents({"deleted_at": {"$exists": False}}),  # Exclude deleted files
            "total_users": db.users.count_documents({}),
            "total_admins": db.users.count_documents({"role": {"$in": ["admin", "superadmin"]}}),
            "active_sessions": 0  # TODO: Implement session tracking
        }
        
        # Calculate actual user file storage size (excluding deleted files)
        file_storage_pipeline = [
            {"$match": {"deleted_at": {"$exists": False}}},
            {"$group": {"_id": None, "total_size": {"$sum": "$size_bytes"}}}
        ]
        file_storage_result = list(db.files.aggregate(file_storage_pipeline))
        user_file_storage = file_storage_result[0]["total_size"] if file_storage_result else 0
        
        # Calculate database metadata size
        db_metadata_size = 0
        try:
            stats = db.command("dbstats")
            db_metadata_size = stats.get("dataSize", 0)
        except Exception:
            pass
        
        await log_admin_activity(
            admin_email=current_admin.email,
            action="view_system_health",
            details="Viewed system health metrics",
            ip_address=get_client_ip(request),
            endpoint="/api/v1/admin/monitoring/system-health"
        )
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": {
                "cpu": {
                    "usage_percent": cpu_percent,
                    "count": cpu_count,
                    "frequency": cpu_freq.current if cpu_freq else 0
                },
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "used": memory.used,
                    "percent": memory.percent,
                    "swap_total": swap.total,
                    "swap_used": swap.used,
                    "swap_percent": swap.percent
                },
                "disk": {
                    "total": disk_usage.total,
                    "used": disk_usage.used,
                    "free": disk_usage.free,
                    "percent": (disk_usage.used / disk_usage.total) * 100
                },
                "network": {
                    "bytes_sent": network.bytes_sent,
                    "bytes_recv": network.bytes_recv,
                    "packets_sent": network.packets_sent,
                    "packets_recv": network.packets_recv
                },
                "uptime": uptime,
                "boot_time": boot_time
            },
            "database": {
                **db_stats,
                "size_bytes": user_file_storage,  # User file storage, not DB metadata
                "metadata_size_bytes": db_metadata_size  # Separate DB metadata size
            }
        }
        
    except Exception as e:
        return {
            "error": f"Failed to get system health metrics: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }

@router.get("/monitoring/api-metrics")
async def get_api_metrics(
    request: Request,
    hours: int = 24,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get API endpoint usage and performance metrics"""
    
    since_time = datetime.utcnow() - timedelta(hours=hours)
    
    # Get admin activity logs for API usage analysis
    api_logs = list(db.admin_activity.aggregate([
        {"$match": {"timestamp": {"$gte": since_time}}},
        {"$group": {
            "_id": "$endpoint",
            "count": {"$sum": 1},
            "actions": {"$push": "$action"}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 20}
    ]))
    
    # Get recent errors from admin activity
    error_logs = list(db.admin_activity.find(
        {
            "timestamp": {"$gte": since_time},
            "details": {"$regex": "error|failed|exception", "$options": "i"}
        },
        {"timestamp": 1, "action": 1, "details": 1, "endpoint": 1}
    ).sort("timestamp", -1).limit(50))
    
    # Calculate hourly request distribution
    hourly_distribution = list(db.admin_activity.aggregate([
        {"$match": {"timestamp": {"$gte": since_time}}},
        {"$group": {
            "_id": {
                "hour": {"$hour": "$timestamp"},
                "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}}
            },
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id.date": 1, "_id.hour": 1}}
    ]))
    
    # Get top admin users by activity
    top_admins = list(db.admin_activity.aggregate([
        {"$match": {"timestamp": {"$gte": since_time}}},
        {"$group": {
            "_id": "$admin_email",
            "total_actions": {"$sum": 1},
            "unique_endpoints": {"$addToSet": "$endpoint"},
            "last_active": {"$max": "$timestamp"}
        }},
        {"$sort": {"total_actions": -1}},
        {"$limit": 10}
    ]))
    
    # Process top admins to get count of unique endpoints
    for admin in top_admins:
        admin["unique_endpoints_count"] = len(admin["unique_endpoints"])
        admin["unique_endpoints"] = admin["unique_endpoints"][:5]  # Limit for display
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_api_metrics",
        details=f"Viewed API metrics for {hours} hours",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/monitoring/api-metrics"
    )
    
    return {
        "period_hours": hours,
        "timestamp": datetime.utcnow().isoformat(),
        "api_usage": {
            "endpoint_stats": api_logs,
            "total_requests": sum(log["count"] for log in api_logs),
            "unique_endpoints": len(api_logs)
        },
        "error_analysis": {
            "recent_errors": error_logs,
            "total_errors": len(error_logs)
        },
        "request_distribution": hourly_distribution,
        "admin_activity": top_admins
    }

@router.get("/monitoring/database-performance")
async def get_database_performance(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get database performance metrics"""
    
    try:
        # Get database statistics
        db_stats = db.command("dbstats")
        
        # Get collection statistics
        collection_stats = {}
        for collection_name in ["files", "users", "admin_activity"]:
            try:
                stats = db.command("collstats", collection_name)
                collection_stats[collection_name] = {
                    "count": stats.get("count", 0),
                    "size": stats.get("size", 0),
                    "storage_size": stats.get("storageSize", 0),
                    "total_index_size": stats.get("totalIndexSize", 0),
                    "avg_obj_size": stats.get("avgObjSize", 0)
                }
            except Exception:
                collection_stats[collection_name] = {"error": "Unable to get stats"}
        
        # Get current operations
        current_ops = []
        try:
            ops = db.command("currentOp")
            current_ops = ops.get("inprog", [])
        except Exception:
            pass
        
        # Calculate query performance metrics
        files_query_start = time.time()
        recent_files = list(db.files.find({}).sort("upload_date", -1).limit(10))
        files_query_time = (time.time() - files_query_start) * 1000
        
        users_query_start = time.time()
        recent_users = list(db.users.find({}).sort("created_at", -1).limit(10))
        users_query_time = (time.time() - users_query_start) * 1000
        
        await log_admin_activity(
            admin_email=current_admin.email,
            action="view_db_performance",
            details="Viewed database performance metrics",
            ip_address=get_client_ip(request),
            endpoint="/api/v1/admin/monitoring/database-performance"
        )
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "database_stats": {
                "db_size": db_stats.get("dataSize", 0),
                "storage_size": db_stats.get("storageSize", 0),
                "index_size": db_stats.get("indexSize", 0),
                "file_size": db_stats.get("fileSize", 0),
                "collections": db_stats.get("collections", 0),
                "objects": db_stats.get("objects", 0),
                "avg_obj_size": db_stats.get("avgObjSize", 0)
            },
            "collection_stats": collection_stats,
            "query_performance": {
                "files_query_time_ms": files_query_time,
                "users_query_time_ms": users_query_time,
                "sample_queries": {
                    "recent_files": len(recent_files),
                    "recent_users": len(recent_users)
                }
            },
            "current_operations": {
                "count": len(current_ops),
                "operations": current_ops[:5]  # Limit to 5 for display
            }
        }
        
    except Exception as e:
        return {
            "error": f"Failed to get database performance metrics: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }

@router.get("/monitoring/error-rates")
async def get_error_rates(
    request: Request,
    hours: int = 24,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get system error rates and patterns"""
    
    since_time = datetime.utcnow() - timedelta(hours=hours)
    
    # Get upload/download failure rates
    upload_stats = list(db.files.aggregate([
        {"$match": {"upload_date": {"$gte": since_time}}},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1}
        }}
    ]))
    
    # Get backup failure rates
    backup_stats = list(db.files.aggregate([
        {"$match": {"upload_date": {"$gte": since_time}}},
        {"$group": {
            "_id": "$backup_status",
            "count": {"$sum": 1}
        }}
    ]))
    
    # Get admin action errors
    admin_errors = list(db.admin_activity.find(
        {
            "timestamp": {"$gte": since_time},
            "$or": [
                {"details": {"$regex": "error|failed|exception", "$options": "i"}},
                {"action": {"$regex": ".*fail.*", "$options": "i"}}
            ]
        },
        {"timestamp": 1, "action": 1, "details": 1, "admin_email": 1}
    ).sort("timestamp", -1).limit(100))
    
    # Calculate error trends by hour
    error_trends = list(db.admin_activity.aggregate([
        {
            "$match": {
                "timestamp": {"$gte": since_time},
                "details": {"$regex": "error|failed|exception", "$options": "i"}
            }
        },
        {
            "$group": {
                "_id": {
                    "hour": {"$hour": "$timestamp"},
                    "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}}
                },
                "error_count": {"$sum": 1}
            }
        },
        {"$sort": {"_id.date": 1, "_id.hour": 1}}
    ]))
    
    # Calculate success rates
    total_uploads = sum(stat["count"] for stat in upload_stats)
    failed_uploads = sum(stat["count"] for stat in upload_stats if stat["_id"] == "failed")
    upload_success_rate = ((total_uploads - failed_uploads) / total_uploads * 100) if total_uploads > 0 else 100
    
    total_backups = sum(stat["count"] for stat in backup_stats)
    failed_backups = sum(stat["count"] for stat in backup_stats if stat["_id"] == "failed")
    backup_success_rate = ((total_backups - failed_backups) / total_backups * 100) if total_backups > 0 else 100
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_error_rates",
        details=f"Viewed error rates for {hours} hours",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/monitoring/error-rates"
    )
    
    return {
        "period_hours": hours,
        "timestamp": datetime.utcnow().isoformat(),
        "upload_metrics": {
            "stats": upload_stats,
            "total_uploads": total_uploads,
            "failed_uploads": failed_uploads,
            "success_rate": round(upload_success_rate, 2)
        },
        "backup_metrics": {
            "stats": backup_stats,
            "total_backups": total_backups,
            "failed_backups": failed_backups,
            "success_rate": round(backup_success_rate, 2)
        },
        "admin_errors": {
            "recent_errors": admin_errors,
            "total_errors": len(admin_errors)
        },
        "error_trends": error_trends
    }

@router.get("/monitoring/system-alerts")
async def get_system_alerts(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get system alerts and warnings"""
    
    alerts = []
    
    try:
        # CPU Alert
        cpu_percent = psutil.cpu_percent(interval=1)
        if cpu_percent > 90:
            alerts.append({
                "type": "critical",
                "category": "cpu",
                "message": f"High CPU usage: {cpu_percent}%",
                "value": cpu_percent,
                "threshold": 90,
                "timestamp": datetime.utcnow().isoformat()
            })
        elif cpu_percent > 70:
            alerts.append({
                "type": "warning",
                "category": "cpu",
                "message": f"Elevated CPU usage: {cpu_percent}%",
                "value": cpu_percent,
                "threshold": 70,
                "timestamp": datetime.utcnow().isoformat()
            })
        
        # Memory Alert
        memory = psutil.virtual_memory()
        if memory.percent > 90:
            alerts.append({
                "type": "critical",
                "category": "memory",
                "message": f"High memory usage: {memory.percent}%",
                "value": memory.percent,
                "threshold": 90,
                "timestamp": datetime.utcnow().isoformat()
            })
        elif memory.percent > 80:
            alerts.append({
                "type": "warning",
                "category": "memory",
                "message": f"Elevated memory usage: {memory.percent}%",
                "value": memory.percent,
                "threshold": 80,
                "timestamp": datetime.utcnow().isoformat()
            })
        
        # Disk Space Alert
        disk_usage = psutil.disk_usage('/')
        disk_percent = (disk_usage.used / disk_usage.total) * 100
        if disk_percent > 95:
            alerts.append({
                "type": "critical",
                "category": "disk",
                "message": f"Very low disk space: {disk_percent:.1f}%",
                "value": disk_percent,
                "threshold": 95,
                "timestamp": datetime.utcnow().isoformat()
            })
        elif disk_percent > 85:
            alerts.append({
                "type": "warning",
                "category": "disk",
                "message": f"Low disk space: {disk_percent:.1f}%",
                "value": disk_percent,
                "threshold": 85,
                "timestamp": datetime.utcnow().isoformat()
            })
        
        # Backup Failure Alert
        recent_time = datetime.utcnow() - timedelta(hours=24)
        failed_backups = db.files.count_documents({
            "backup_status": "failed",
            "backup_failed_at": {"$gte": recent_time}
        })
        
        if failed_backups > 20:
            alerts.append({
                "type": "warning",
                "category": "backup",
                "message": f"High backup failure rate: {failed_backups} failures in 24h",
                "value": failed_backups,
                "threshold": 20,
                "timestamp": datetime.utcnow().isoformat()
            })
        
        # Queue Backup Alert
        queue_size = db.files.count_documents({
            "$or": [
                {"backup_status": "none"},
                {"backup_status": {"$exists": False}},
                {"backup_status": "in_progress"}
            ]
        })
        
        if queue_size > 1000:
            alerts.append({
                "type": "warning",
                "category": "backup_queue",
                "message": f"Large backup queue: {queue_size} files pending",
                "value": queue_size,
                "threshold": 1000,
                "timestamp": datetime.utcnow().isoformat()
            })
        
        await log_admin_activity(
            admin_email=current_admin.email,
            action="view_system_alerts",
            details=f"Viewed system alerts - {len(alerts)} alerts found",
            ip_address=get_client_ip(request),
            endpoint="/api/v1/admin/monitoring/system-alerts"
        )
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "alerts": alerts,
            "alert_counts": {
                "critical": len([a for a in alerts if a["type"] == "critical"]),
                "warning": len([a for a in alerts if a["type"] == "warning"]),
                "total": len(alerts)
            }
        }
        
    except Exception as e:
        return {
            "error": f"Failed to get system alerts: {str(e)}",
            "timestamp": datetime.utcnow().isoformat(),
            "alerts": [],
            "alert_counts": {"critical": 0, "warning": 0, "total": 0}
        }

# ================================
# LOGS MANAGEMENT ENDPOINTS
# ================================

@router.get("/logs/admin-activity")
async def get_admin_activity_logs(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    admin_email: str = Query(None),
    action_filter: str = Query(None),
    days: int = Query(7, ge=1, le=365),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get admin activity logs with filtering and pagination"""
    
    skip = (page - 1) * limit
    since_time = datetime.utcnow() - timedelta(days=days)
    
    # Build query
    query = {"timestamp": {"$gte": since_time}}
    if admin_email:
        query["admin_email"] = {"$regex": admin_email, "$options": "i"}
    if action_filter:
        query["action"] = {"$regex": action_filter, "$options": "i"}
    
    # Get logs
    logs = list(db.admin_activity.find(
        query,
        {
            "timestamp": 1, "admin_email": 1, "action": 1, 
            "details": 1, "ip_address": 1, "endpoint": 1
        }
    ).sort("timestamp", -1).skip(skip).limit(limit))
    
    total_logs = db.admin_activity.count_documents(query)
    
    # Get activity summary
    activity_summary = list(db.admin_activity.aggregate([
        {"$match": query},
        {"$group": {
            "_id": "$action",
            "count": {"$sum": 1},
            "last_occurrence": {"$max": "$timestamp"}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]))
    
    # Get top admins
    top_admins = list(db.admin_activity.aggregate([
        {"$match": query},
        {"$group": {
            "_id": "$admin_email",
            "total_actions": {"$sum": 1},
            "last_active": {"$max": "$timestamp"},
            "actions": {"$addToSet": "$action"}
        }},
        {"$sort": {"total_actions": -1}},
        {"$limit": 10}
    ]))
    
    for admin in top_admins:
        admin["unique_actions"] = len(admin["actions"])
        admin["actions"] = admin["actions"][:5]  # Limit for display
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_admin_logs",
        details=f"Viewed admin activity logs - page {page}, period {days} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/logs/admin-activity"
    )
    
    return {
        "logs": logs,
        "total_logs": total_logs,
        "page": page,
        "limit": limit,
        "total_pages": (total_logs + limit - 1) // limit,
        "period_days": days,
        "activity_summary": activity_summary,
        "top_admins": top_admins
    }

@router.get("/logs/application-errors")
async def get_application_error_logs(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    severity: str = Query(None),
    days: int = Query(7, ge=1, le=365),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get application error logs with filtering"""
    
    skip = (page - 1) * limit
    since_time = datetime.utcnow() - timedelta(days=days)
    
    # Build query for errors from admin activity
    query = {
        "timestamp": {"$gte": since_time},
        "$or": [
            {"details": {"$regex": "error|failed|exception", "$options": "i"}},
            {"action": {"$regex": ".*fail.*", "$options": "i"}}
        ]
    }
    
    if severity:
        if severity == "critical":
            query["$or"].append({"details": {"$regex": "critical|fatal", "$options": "i"}})
        elif severity == "warning":
            query["$or"].append({"details": {"$regex": "warning|warn", "$options": "i"}})
    
    # Get error logs
    error_logs = list(db.admin_activity.find(
        query,
        {
            "timestamp": 1, "admin_email": 1, "action": 1,
            "details": 1, "ip_address": 1, "endpoint": 1
        }
    ).sort("timestamp", -1).skip(skip).limit(limit))
    
    total_errors = db.admin_activity.count_documents(query)
    
    # Analyze error patterns
    error_patterns = list(db.admin_activity.aggregate([
        {"$match": query},
        {"$group": {
            "_id": "$endpoint",
            "error_count": {"$sum": 1},
            "last_error": {"$max": "$timestamp"},
            "error_types": {"$addToSet": "$action"}
        }},
        {"$sort": {"error_count": -1}},
        {"$limit": 10}
    ]))
    
    # Get hourly error distribution
    error_timeline = list(db.admin_activity.aggregate([
        {"$match": query},
        {"$group": {
            "_id": {
                "hour": {"$hour": "$timestamp"},
                "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}}
            },
            "error_count": {"$sum": 1}
        }},
        {"$sort": {"_id.date": 1, "_id.hour": 1}}
    ]))
    
    # Get top error types
    error_types = list(db.admin_activity.aggregate([
        {"$match": query},
        {"$group": {
            "_id": "$action",
            "count": {"$sum": 1},
            "recent_occurrence": {"$max": "$timestamp"}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 15}
    ]))
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_error_logs",
        details=f"Viewed application error logs - page {page}, period {days} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/logs/application-errors"
    )
    
    return {
        "error_logs": error_logs,
        "total_errors": total_errors,
        "page": page,
        "limit": limit,
        "total_pages": (total_errors + limit - 1) // limit,
        "period_days": days,
        "error_patterns": error_patterns,
        "error_timeline": error_timeline,
        "error_types": error_types
    }

@router.get("/logs/system-access")
async def get_system_access_logs(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    ip_address: str = Query(None),
    days: int = Query(7, ge=1, le=365),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get system access logs (login attempts, auth events)"""
    
    skip = (page - 1) * limit
    since_time = datetime.utcnow() - timedelta(days=days)
    
    # Build query for access-related events
    query = {
        "timestamp": {"$gte": since_time},
        "action": {"$in": ["login", "login_failed", "logout", "token_refresh", "password_reset", "create_admin"]}
    }
    
    if ip_address:
        query["ip_address"] = {"$regex": ip_address, "$options": "i"}
    
    # Get access logs
    access_logs = list(db.admin_activity.find(
        query,
        {
            "timestamp": 1, "admin_email": 1, "action": 1,
            "details": 1, "ip_address": 1, "endpoint": 1
        }
    ).sort("timestamp", -1).skip(skip).limit(limit))
    
    total_access = db.admin_activity.count_documents(query)
    
    # Get login statistics
    login_stats = list(db.admin_activity.aggregate([
        {
            "$match": {
                "timestamp": {"$gte": since_time},
                "action": {"$in": ["login", "login_failed"]}
            }
        },
        {"$group": {
            "_id": "$action",
            "count": {"$sum": 1}
        }}
    ]))
    
    successful_logins = next((stat["count"] for stat in login_stats if stat["_id"] == "login"), 0)
    failed_logins = next((stat["count"] for stat in login_stats if stat["_id"] == "login_failed"), 0)
    total_login_attempts = successful_logins + failed_logins
    success_rate = (successful_logins / total_login_attempts * 100) if total_login_attempts > 0 else 100
    
    # Get top IP addresses
    top_ips = list(db.admin_activity.aggregate([
        {"$match": query},
        {"$group": {
            "_id": "$ip_address",
            "access_count": {"$sum": 1},
            "last_access": {"$max": "$timestamp"},
            "admins": {"$addToSet": "$admin_email"}
        }},
        {"$sort": {"access_count": -1}},
        {"$limit": 10}
    ]))
    
    for ip in top_ips:
        ip["unique_admins"] = len(ip["admins"])
        ip["admins"] = ip["admins"][:3]  # Limit for display
    
    # Get daily access pattern
    daily_access = list(db.admin_activity.aggregate([
        {"$match": query},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
            "total_access": {"$sum": 1},
            "unique_admins": {"$addToSet": "$admin_email"}
        }},
        {"$sort": {"_id": 1}}
    ]))
    
    for day in daily_access:
        day["unique_admin_count"] = len(day["unique_admins"])
        day["unique_admins"] = day["unique_admins"][:5]  # Limit for display
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_access_logs",
        details=f"Viewed system access logs - page {page}, period {days} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/logs/system-access"
    )
    
    return {
        "access_logs": access_logs,
        "total_access": total_access,
        "page": page,
        "limit": limit,
        "total_pages": (total_access + limit - 1) // limit,
        "period_days": days,
        "login_statistics": {
            "successful_logins": successful_logins,
            "failed_logins": failed_logins,
            "success_rate": round(success_rate, 2),
            "total_attempts": total_login_attempts
        },
        "top_ips": top_ips,
        "daily_access": daily_access
    }

@router.post("/logs/export")
async def export_logs(
    request: Request,
    log_type: str = Query(..., pattern="^(admin-activity|errors|access)$"),
    format: str = Query("csv", pattern="^(csv|json)$"),
    days: int = Query(7, ge=1, le=90),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Export logs in CSV or JSON format"""
    
    from fastapi.responses import StreamingResponse
    import csv
    import json
    import io
    
    since_time = datetime.utcnow() - timedelta(days=days)
    
    # Build query based on log type
    if log_type == "admin-activity":
        query = {"timestamp": {"$gte": since_time}}
        fields = {"timestamp": 1, "admin_email": 1, "action": 1, "details": 1, "ip_address": 1, "endpoint": 1}
    elif log_type == "errors":
        query = {
            "timestamp": {"$gte": since_time},
            "$or": [
                {"details": {"$regex": "error|failed|exception", "$options": "i"}},
                {"action": {"$regex": ".*fail.*", "$options": "i"}}
            ]
        }
        fields = {"timestamp": 1, "admin_email": 1, "action": 1, "details": 1, "ip_address": 1, "endpoint": 1}
    elif log_type == "access":
        query = {
            "timestamp": {"$gte": since_time},
            "action": {"$in": ["login", "login_failed", "logout", "token_refresh", "password_reset"]}
        }
        fields = {"timestamp": 1, "admin_email": 1, "action": 1, "details": 1, "ip_address": 1, "endpoint": 1}
    
    # Get logs (limit to prevent memory issues)
    logs = list(db.admin_activity.find(query, fields).sort("timestamp", -1).limit(5000))
    
    # Prepare data for export
    export_data = []
    for log in logs:
        export_data.append({
            "timestamp": log["timestamp"].isoformat() if isinstance(log["timestamp"], datetime) else str(log["timestamp"]),
            "admin_email": log.get("admin_email", ""),
            "action": log.get("action", ""),
            "details": log.get("details", ""),
            "ip_address": log.get("ip_address", ""),
            "endpoint": log.get("endpoint", "")
        })
    
    # Generate export content
    if format == "csv":
        output = io.StringIO()
        if export_data:
            writer = csv.DictWriter(output, fieldnames=export_data[0].keys())
            writer.writeheader()
            writer.writerows(export_data)
        
        content = output.getvalue()
        output.close()
        
        filename = f"{log_type}_logs_{days}days_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        media_type = "text/csv"
    else:  # JSON
        content = json.dumps({
            "export_info": {
                "log_type": log_type,
                "period_days": days,
                "export_date": datetime.utcnow().isoformat(),
                "total_records": len(export_data)
            },
            "logs": export_data
        }, indent=2)
        
        filename = f"{log_type}_logs_{days}days_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        media_type = "application/json"
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="export_logs",
        details=f"Exported {log_type} logs for {days} days in {format} format - {len(export_data)} records",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/logs/export"
    )
    
    # Create streaming response
    def generate():
        yield content
    
    return StreamingResponse(
        generate(),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.delete("/logs/cleanup")
async def cleanup_old_logs(
    request: Request,
    days: int = Query(90, ge=30, le=365),
    current_admin: AdminUserInDB = Depends(get_current_superadmin)  # Only superadmin can cleanup
):
    """Clean up old log entries (superadmin only)"""
    
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Count logs to be deleted
    logs_to_delete = db.admin_activity.count_documents({"timestamp": {"$lt": cutoff_date}})
    
    if logs_to_delete == 0:
        return {
            "message": "No logs found older than specified period",
            "logs_deleted": 0,
            "cutoff_date": cutoff_date.isoformat()
        }
    
    # Delete old logs
    delete_result = db.admin_activity.delete_many({"timestamp": {"$lt": cutoff_date}})
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="cleanup_logs",
        details=f"Cleaned up {delete_result.deleted_count} log entries older than {days} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/logs/cleanup"
    )
    
    return {
        "message": f"Successfully cleaned up old log entries",
        "logs_deleted": delete_result.deleted_count,
        "cutoff_date": cutoff_date.isoformat(),
        "retention_days": days
    }

# ================================
# API MONITORING ENDPOINTS
# ================================

@router.get("/api-monitoring/endpoint-usage")
async def get_endpoint_usage_metrics(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    endpoint_filter: str = Query(None),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get detailed API endpoint usage metrics and statistics"""
    
    since_time = datetime.utcnow() - timedelta(hours=hours)
    
    # Build query
    query = {"timestamp": {"$gte": since_time}}
    if endpoint_filter:
        query["endpoint"] = {"$regex": endpoint_filter, "$options": "i"}
    
    # Get endpoint usage statistics
    endpoint_stats = list(db.admin_activity.aggregate([
        {"$match": query},
        {"$group": {
            "_id": "$endpoint",
            "total_requests": {"$sum": 1},
            "unique_admins": {"$addToSet": "$admin_email"},
            "unique_ips": {"$addToSet": "$ip_address"},
            "first_request": {"$min": "$timestamp"},
            "last_request": {"$max": "$timestamp"},
            "actions": {"$addToSet": "$action"}
        }},
        {"$sort": {"total_requests": -1}},
        {"$limit": 50}
    ]))
    
    # Process endpoint stats
    for stat in endpoint_stats:
        stat["unique_admin_count"] = len(stat["unique_admins"])
        stat["unique_ip_count"] = len(stat["unique_ips"])
        stat["unique_action_count"] = len(stat["actions"])
        stat["unique_admins"] = stat["unique_admins"][:5]  # Limit for display
        stat["unique_ips"] = stat["unique_ips"][:5]  # Limit for display
        stat["actions"] = stat["actions"][:10]  # Limit for display
    
    # Get hourly request distribution
    hourly_requests = list(db.admin_activity.aggregate([
        {"$match": query},
        {"$group": {
            "_id": {
                "hour": {"$hour": "$timestamp"},
                "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}}
            },
            "request_count": {"$sum": 1},
            "unique_endpoints": {"$addToSet": "$endpoint"}
        }},
        {"$sort": {"_id.date": 1, "_id.hour": 1}}
    ]))
    
    for hour in hourly_requests:
        hour["unique_endpoint_count"] = len(hour["unique_endpoints"])
    
    # Get most active endpoints by hour
    peak_hours = list(db.admin_activity.aggregate([
        {"$match": query},
        {"$group": {
            "_id": {"$hour": "$timestamp"},
            "request_count": {"$sum": 1}
        }},
        {"$sort": {"request_count": -1}},
        {"$limit": 5}
    ]))
    
    # Calculate total metrics
    total_requests = sum(stat["total_requests"] for stat in endpoint_stats)
    unique_endpoints = len(endpoint_stats)
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_endpoint_usage",
        details=f"Viewed API endpoint usage for {hours} hours",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/api-monitoring/endpoint-usage"
    )
    
    return {
        "period_hours": hours,
        "timestamp": datetime.utcnow().isoformat(),
        "summary": {
            "total_requests": total_requests,
            "unique_endpoints": unique_endpoints,
            "average_requests_per_hour": round(total_requests / hours, 2) if hours > 0 else 0
        },
        "endpoint_stats": endpoint_stats,
        "hourly_distribution": hourly_requests,
        "peak_hours": peak_hours
    }

@router.get("/api-monitoring/response-times")
async def get_response_time_metrics(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get API response time metrics and performance analysis"""
    
    since_time = datetime.utcnow() - timedelta(hours=hours)
    
    # Simulate response time data based on endpoint complexity
    # In a real implementation, this would come from actual monitoring data
    endpoint_performance = []
    
    # Get endpoint data and simulate response times
    endpoints = list(db.admin_activity.aggregate([
        {"$match": {"timestamp": {"$gte": since_time}}},
        {"$group": {
            "_id": "$endpoint",
            "request_count": {"$sum": 1},
            "actions": {"$addToSet": "$action"}
        }},
        {"$sort": {"request_count": -1}},
        {"$limit": 20}
    ]))
    
    for endpoint in endpoints:
        endpoint_name = endpoint["_id"] or "unknown"
        request_count = endpoint["request_count"]
        
        # Simulate response times based on endpoint type
        if "monitoring" in endpoint_name.lower():
            avg_response_time = 150 + (request_count * 0.1)  # Monitoring endpoints
        elif "backup" in endpoint_name.lower():
            avg_response_time = 300 + (request_count * 0.2)  # Backup endpoints
        elif "files" in endpoint_name.lower():
            avg_response_time = 200 + (request_count * 0.15)  # File endpoints
        elif "auth" in endpoint_name.lower():
            avg_response_time = 100 + (request_count * 0.05)  # Auth endpoints
        else:
            avg_response_time = 180 + (request_count * 0.1)  # Default
        
        # Add some variance
        min_time = max(50, avg_response_time - 50)
        max_time = avg_response_time + 100
        p95_time = avg_response_time + 30
        
        endpoint_performance.append({
            "endpoint": endpoint_name,
            "request_count": request_count,
            "avg_response_time_ms": round(avg_response_time, 2),
            "min_response_time_ms": round(min_time, 2),
            "max_response_time_ms": round(max_time, 2),
            "p95_response_time_ms": round(p95_time, 2),
            "status": "good" if avg_response_time < 200 else "warning" if avg_response_time < 500 else "slow"
        })
    
    # Calculate overall performance metrics
    if endpoint_performance:
        avg_overall = sum(ep["avg_response_time_ms"] for ep in endpoint_performance) / len(endpoint_performance)
        slowest_endpoint = max(endpoint_performance, key=lambda x: x["avg_response_time_ms"])
        fastest_endpoint = min(endpoint_performance, key=lambda x: x["avg_response_time_ms"])
    else:
        avg_overall = 0
        slowest_endpoint = None
        fastest_endpoint = None
    
    # Generate hourly performance trends (simulated)
    performance_trends = []
    for i in range(min(hours, 24)):  # Last 24 hours or specified hours
        hour_time = datetime.utcnow() - timedelta(hours=i)
        avg_time = avg_overall + (i * 5) + (10 if hour_time.hour in [9, 10, 14, 15] else 0)  # Peak hours
        performance_trends.append({
            "hour": hour_time.strftime("%Y-%m-%d %H:00"),
            "avg_response_time": round(avg_time, 2),
            "request_count": max(1, len(endpoint_performance) - i)
        })
    
    performance_trends.reverse()  # Chronological order
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_response_times",
        details=f"Viewed API response time metrics for {hours} hours",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/api-monitoring/response-times"
    )
    
    return {
        "period_hours": hours,
        "timestamp": datetime.utcnow().isoformat(),
        "overall_metrics": {
            "average_response_time_ms": round(avg_overall, 2),
            "total_endpoints_monitored": len(endpoint_performance),
            "slowest_endpoint": slowest_endpoint,
            "fastest_endpoint": fastest_endpoint
        },
        "endpoint_performance": endpoint_performance,
        "performance_trends": performance_trends
    }

@router.get("/api-monitoring/error-rates")
async def get_api_error_rates(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get API error rates by endpoint and error analysis"""
    
    since_time = datetime.utcnow() - timedelta(hours=hours)
    
    # Get error statistics by endpoint
    error_stats = list(db.admin_activity.aggregate([
        {
            "$match": {
                "timestamp": {"$gte": since_time},
                "$or": [
                    {"details": {"$regex": "error|failed|exception", "$options": "i"}},
                    {"action": {"$regex": ".*fail.*", "$options": "i"}}
                ]
            }
        },
        {
            "$group": {
                "_id": "$endpoint",
                "error_count": {"$sum": 1},
                "error_types": {"$addToSet": "$action"},
                "last_error": {"$max": "$timestamp"},
                "affected_admins": {"$addToSet": "$admin_email"}
            }
        },
        {"$sort": {"error_count": -1}},
        {"$limit": 20}
    ]))
    
    # Get total requests by endpoint for error rate calculation
    total_requests = list(db.admin_activity.aggregate([
        {"$match": {"timestamp": {"$gte": since_time}}},
        {
            "$group": {
                "_id": "$endpoint",
                "total_requests": {"$sum": 1}
            }
        }
    ]))
    
    # Merge error stats with total requests
    request_map = {req["_id"]: req["total_requests"] for req in total_requests}
    
    for error_stat in error_stats:
        endpoint = error_stat["_id"]
        total = request_map.get(endpoint, error_stat["error_count"])
        error_rate = (error_stat["error_count"] / total * 100) if total > 0 else 0
        
        error_stat["total_requests"] = total
        error_stat["error_rate_percent"] = round(error_rate, 2)
        error_stat["error_type_count"] = len(error_stat["error_types"])
        error_stat["affected_admin_count"] = len(error_stat["affected_admins"])
        error_stat["status"] = "critical" if error_rate > 10 else "warning" if error_rate > 5 else "normal"
    
    # Get error timeline
    error_timeline = list(db.admin_activity.aggregate([
        {
            "$match": {
                "timestamp": {"$gte": since_time},
                "$or": [
                    {"details": {"$regex": "error|failed|exception", "$options": "i"}},
                    {"action": {"$regex": ".*fail.*", "$options": "i"}}
                ]
            }
        },
        {
            "$group": {
                "_id": {
                    "hour": {"$hour": "$timestamp"},
                    "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}}
                },
                "error_count": {"$sum": 1},
                "unique_endpoints": {"$addToSet": "$endpoint"}
            }
        },
        {"$sort": {"_id.date": 1, "_id.hour": 1}}
    ]))
    
    # Get most common error types
    common_errors = list(db.admin_activity.aggregate([
        {
            "$match": {
                "timestamp": {"$gte": since_time},
                "$or": [
                    {"details": {"$regex": "error|failed|exception", "$options": "i"}},
                    {"action": {"$regex": ".*fail.*", "$options": "i"}}
                ]
            }
        },
        {
            "$group": {
                "_id": "$action",
                "count": {"$sum": 1},
                "endpoints": {"$addToSet": "$endpoint"},
                "recent_occurrence": {"$max": "$timestamp"}
            }
        },
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]))
    
    for error in common_errors:
        error["affected_endpoint_count"] = len(error["endpoints"])
    
    # Calculate overall error rate
    total_all_requests = sum(req["total_requests"] for req in total_requests)
    total_errors = sum(stat["error_count"] for stat in error_stats)
    overall_error_rate = (total_errors / total_all_requests * 100) if total_all_requests > 0 else 0
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_api_error_rates",
        details=f"Viewed API error rates for {hours} hours",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/api-monitoring/error-rates"
    )
    
    return {
        "period_hours": hours,
        "timestamp": datetime.utcnow().isoformat(),
        "overall_metrics": {
            "total_requests": total_all_requests,
            "total_errors": total_errors,
            "overall_error_rate_percent": round(overall_error_rate, 2),
            "endpoints_with_errors": len(error_stats)
        },
        "endpoint_error_rates": error_stats,
        "error_timeline": error_timeline,
        "common_error_types": common_errors
    }

@router.get("/api-monitoring/rate-limits")
async def get_rate_limit_metrics(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get rate limiting metrics and potential abuse detection"""
    
    since_time = datetime.utcnow() - timedelta(hours=hours)
    
    # Analyze request patterns by IP and admin
    ip_analysis = list(db.admin_activity.aggregate([
        {"$match": {"timestamp": {"$gte": since_time}}},
        {
            "$group": {
                "_id": "$ip_address",
                "total_requests": {"$sum": 1},
                "unique_admins": {"$addToSet": "$admin_email"},
                "unique_endpoints": {"$addToSet": "$endpoint"},
                "first_request": {"$min": "$timestamp"},
                "last_request": {"$max": "$timestamp"}
            }
        },
        {"$sort": {"total_requests": -1}},
        {"$limit": 50}
    ]))
    
    # Calculate request rates and identify potential issues
    for ip_stat in ip_analysis:
        time_span = (ip_stat["last_request"] - ip_stat["first_request"]).total_seconds()
        requests_per_hour = (ip_stat["total_requests"] / (time_span / 3600)) if time_span > 0 else ip_stat["total_requests"]
        
        ip_stat["unique_admin_count"] = len(ip_stat["unique_admins"])
        ip_stat["unique_endpoint_count"] = len(ip_stat["unique_endpoints"])
        ip_stat["requests_per_hour"] = round(requests_per_hour, 2)
        ip_stat["time_span_hours"] = round(time_span / 3600, 2)
        
        # Flag potential issues
        if requests_per_hour > 1000:
            ip_stat["risk_level"] = "high"
        elif requests_per_hour > 500:
            ip_stat["risk_level"] = "medium"
        else:
            ip_stat["risk_level"] = "low"
    
    # Analyze admin activity patterns
    admin_analysis = list(db.admin_activity.aggregate([
        {"$match": {"timestamp": {"$gte": since_time}}},
        {
            "$group": {
                "_id": "$admin_email",
                "total_requests": {"$sum": 1},
                "unique_ips": {"$addToSet": "$ip_address"},
                "unique_endpoints": {"$addToSet": "$endpoint"},
                "actions": {"$addToSet": "$action"},
                "first_request": {"$min": "$timestamp"},
                "last_request": {"$max": "$timestamp"}
            }
        },
        {"$sort": {"total_requests": -1}},
        {"$limit": 20}
    ]))
    
    for admin_stat in admin_analysis:
        time_span = (admin_stat["last_request"] - admin_stat["first_request"]).total_seconds()
        requests_per_hour = (admin_stat["total_requests"] / (time_span / 3600)) if time_span > 0 else admin_stat["total_requests"]
        
        admin_stat["unique_ip_count"] = len(admin_stat["unique_ips"])
        admin_stat["unique_endpoint_count"] = len(admin_stat["unique_endpoints"])
        admin_stat["unique_action_count"] = len(admin_stat["actions"])
        admin_stat["requests_per_hour"] = round(requests_per_hour, 2)
        admin_stat["time_span_hours"] = round(time_span / 3600, 2)
        
        # Flag unusual patterns
        if admin_stat["unique_ip_count"] > 5:
            admin_stat["flag"] = "multiple_ips"
        elif requests_per_hour > 200:
            admin_stat["flag"] = "high_activity"
        else:
            admin_stat["flag"] = "normal"
    
    # Get peak activity periods
    peak_periods = list(db.admin_activity.aggregate([
        {"$match": {"timestamp": {"$gte": since_time}}},
        {
            "$group": {
                "_id": {
                    "hour": {"$hour": "$timestamp"},
                    "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}}
                },
                "request_count": {"$sum": 1},
                "unique_ips": {"$addToSet": "$ip_address"},
                "unique_admins": {"$addToSet": "$admin_email"}
            }
        },
        {"$sort": {"request_count": -1}},
        {"$limit": 10}
    ]))
    
    for period in peak_periods:
        period["unique_ip_count"] = len(period["unique_ips"])
        period["unique_admin_count"] = len(period["unique_admins"])
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_rate_limits",
        details=f"Viewed rate limit metrics for {hours} hours",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/api-monitoring/rate-limits"
    )
    
    return {
        "period_hours": hours,
        "timestamp": datetime.utcnow().isoformat(),
        "ip_analysis": ip_analysis,
        "admin_analysis": admin_analysis,
        "peak_periods": peak_periods,
        "recommendations": {
            "high_risk_ips": len([ip for ip in ip_analysis if ip.get("risk_level") == "high"]),
            "active_admins": len(admin_analysis),
            "max_requests_per_hour": max([ip["requests_per_hour"] for ip in ip_analysis], default=0)
        }
    }

@router.get("/api-monitoring/third-party-status")
async def get_third_party_api_status(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get status of third-party APIs and external services"""
    
    external_services = []
    
    try:
        # Check Google Drive API status (simulated based on recent backup activities)
        recent_backups = db.files.count_documents({
            "backup_started_at": {"$gte": datetime.utcnow() - timedelta(hours=1)},
            "backup_status": "completed"
        })
        recent_backup_failures = db.files.count_documents({
            "backup_failed_at": {"$gte": datetime.utcnow() - timedelta(hours=1)},
            "backup_status": "failed"
        })
        
        total_recent_backups = recent_backups + recent_backup_failures
        backup_success_rate = (recent_backups / total_recent_backups * 100) if total_recent_backups > 0 else 100
        
        google_drive_status = {
            "service": "Google Drive API",
            "status": "operational" if backup_success_rate > 90 else "degraded" if backup_success_rate > 50 else "outage",
            "last_check": datetime.utcnow().isoformat(),
            "metrics": {
                "recent_operations": total_recent_backups,
                "success_rate": round(backup_success_rate, 2),
                "response_time_ms": 250  # Simulated
            }
        }
        external_services.append(google_drive_status)
        
        # Check Hetzner API status (simulated)
        hetzner_backups = db.files.count_documents({
            "backup_status": "completed",
            "backup_location": "hetzner",
            "backup_completed_at": {"$gte": datetime.utcnow() - timedelta(hours=1)}
        })
        
        hetzner_status = {
            "service": "Hetzner WebDAV API",
            "status": "operational" if hetzner_backups > 0 else "unknown",
            "last_check": datetime.utcnow().isoformat(),
            "metrics": {
                "recent_operations": hetzner_backups,
                "success_rate": 95.0,  # Simulated
                "response_time_ms": 180  # Simulated
            }
        }
        external_services.append(hetzner_status)
        
        # Check Database status
        db_status = {
            "service": "MongoDB Database",
            "status": "operational",
            "last_check": datetime.utcnow().isoformat(),
            "metrics": {
                "connection_pool": 10,  # Simulated
                "active_connections": 3,  # Simulated
                "response_time_ms": 15   # Simulated
            }
        }
        external_services.append(db_status)
        
    except Exception as e:
        external_services.append({
            "service": "Monitoring Error",
            "status": "error",
            "error": str(e),
            "last_check": datetime.utcnow().isoformat()
        })
    
    # Calculate overall health
    operational_count = len([s for s in external_services if s["status"] == "operational"])
    total_services = len(external_services)
    overall_health = (operational_count / total_services * 100) if total_services > 0 else 0
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_third_party_status",
        details="Viewed third-party API status",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/api-monitoring/third-party-status"
    )
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "overall_health": {
            "status": "healthy" if overall_health > 80 else "degraded" if overall_health > 50 else "critical",
            "operational_services": operational_count,
            "total_services": total_services,
            "health_percentage": round(overall_health, 2)
        },
        "external_services": external_services
    }

@router.get("/processes/status", response_model=Dict[str, Any])
async def get_process_queue_status(current_admin: AdminUserInDB = Depends(get_current_admin)):
    """Get current background process queue status"""
    try:
        queue_status = background_process_manager.get_queue_status()
        return {
            "success": True,
            "queue_status": queue_status,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting process queue status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get process queue status"
        )

@router.get("/processes/active", response_model=List[Dict[str, Any]])
async def get_active_processes(
    admin_only: bool = Query(False, description="Show only admin-initiated processes"),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get currently active background processes"""
    try:
        active_processes = background_process_manager.get_active_processes(admin_only=admin_only)
        return [process.to_dict() for process in active_processes]
    except Exception as e:
        logger.error(f"Error getting active processes: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get active processes"
        )

@router.get("/processes/priority-info", response_model=Dict[str, Any])
async def get_priority_system_info(current_admin: AdminUserInDB = Depends(get_current_admin)):
    """Get information about the priority system and how it works"""
    return {
        "priority_system": {
            "description": "Priority-based background process management system",
            "admin_priority": "Admin operations get priority 1-2 (Critical/High)",
            "user_priority": "User operations get priority 3-4 (Normal/Low)",
            "admin_workers": "2 dedicated admin workers for high-priority tasks",
            "user_workers": "3 user workers for normal operations",
            "queue_behavior": "Admin workers can help with user tasks when admin queue is empty"
        },
        "process_types": {
            "admin_quota_refresh": "Google Drive account quota updates",
            "admin_storage_cleanup": "Storage optimization and cleanup",
            "admin_backup_operation": "Backup and restore operations",
            "user_file_upload": "File upload processing",
            "user_file_download": "File download processing",
            "user_batch_operation": "Batch file operations"
        },
        "priority_levels": {
            "1": "CRITICAL - Admin operations that must complete immediately",
            "2": "HIGH - Admin operations with high priority",
            "3": "NORMAL - Regular user operations",
            "4": "LOW - Background maintenance tasks"
        }
    }

@router.get("/processes/{process_id}", response_model=Dict[str, Any])
async def get_process_details(
    process_id: str,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get details of a specific background process"""
    try:
        process = background_process_manager.get_process(process_id)
        if not process:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Process not found"
            )
        return process.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting process details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get process details"
        )

@router.post("/processes/{process_id}/cancel", response_model=Dict[str, Any])
async def cancel_process(
    process_id: str,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Cancel a running background process"""
    try:
        success = background_process_manager.cancel_process(process_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Process cannot be cancelled or not found"
            )
        
        return {
            "success": True,
            "message": f"Process {process_id} cancelled successfully",
            "process_id": process_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling process: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel process"
        )

@router.post("/processes/refresh-quota", response_model=Dict[str, Any])
async def trigger_quota_refresh(
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Trigger a manual quota refresh for all Google Drive accounts (Admin Priority)"""
    try:
        # Add high-priority admin process
        process_id = background_process_manager.add_process(
            process_type=ProcessType.ADMIN_QUOTA_REFRESH,
            priority=ProcessPriority.HIGH,
            description="Manual quota refresh triggered by admin",
            admin_initiated=True,
            metadata={"admin_email": current_admin.email}
        )
        
        return {
            "success": True,
            "message": "Quota refresh process started with high priority",
            "process_id": process_id,
            "priority": "HIGH"
        }
    except Exception as e:
        logger.error(f"Error triggering quota refresh: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start quota refresh process"
        )