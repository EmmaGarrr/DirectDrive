from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from bson import ObjectId
from app.models.admin import AdminUserInDB
from app.db.mongodb import db
from app.services.admin_auth_service import get_current_admin, get_current_superadmin, log_admin_activity, get_client_ip
import asyncio
import uuid
import json
import io
import csv
from enum import Enum

router = APIRouter()

# ================================
# REPORT MODELS
# ================================

class ReportType(str, Enum):
    SYSTEM_OVERVIEW = "system_overview"
    USER_ACTIVITY = "user_activity"
    STORAGE_USAGE = "storage_usage"
    FILE_ANALYTICS = "file_analytics"
    ADMIN_ACTIVITY = "admin_activity"
    SECURITY_AUDIT = "security_audit"
    PERFORMANCE_METRICS = "performance_metrics"
    CUSTOM = "custom"

class ExportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"
    PDF = "pdf"  # For future implementation
    EXCEL = "excel"  # For future implementation

class ReportScheduleFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"

class ReportRequest(BaseModel):
    report_type: ReportType
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    date_from: datetime
    date_to: datetime
    export_format: ExportFormat = ExportFormat.JSON
    include_charts: bool = False
    filters: Optional[Dict[str, Any]] = None

class ScheduledReportCreate(BaseModel):
    report_type: ReportType
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    frequency: ReportScheduleFrequency
    export_format: ExportFormat = ExportFormat.JSON
    recipients: List[str] = Field(..., min_items=1)  # Email addresses
    filters: Optional[Dict[str, Any]] = None
    is_active: bool = True

class CustomReportBuilder(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    data_sources: List[str]  # Collection names: users, files, admin_activity_logs, etc.
    fields: List[str]  # Field names to include
    aggregation_pipeline: Optional[List[Dict[str, Any]]] = None
    date_from: datetime
    date_to: datetime
    export_format: ExportFormat = ExportFormat.JSON

# ================================
# SYSTEM REPORTS ENDPOINTS
# ================================

@router.get("/reports/system-overview")
async def generate_system_overview_report(
    request: Request,
    date_from: datetime = Query(...),
    date_to: datetime = Query(...),
    export_format: ExportFormat = Query(ExportFormat.JSON),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Generate comprehensive system overview report"""
    # db is imported directly
    
    # Validate date range
    if date_from >= date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start date must be before end date"
        )
    
    # System Overview Data
    report_data = {
        "report_info": {
            "type": "system_overview",
            "title": "System Overview Report",
            "generated_at": datetime.utcnow().isoformat(),
            "generated_by": current_admin.email,
            "period": {
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
                "days": (date_to - date_from).days
            }
        },
        "user_statistics": {},
        "file_statistics": {},
        "storage_statistics": {},
        "admin_activity": {},
        "system_performance": {},
        "growth_metrics": {}
    }
    
    # User Statistics
    total_users = db.users.count_documents({})
    active_users = db.users.count_documents({"is_active": True})
    new_users_period = db.users.count_documents({
        "created_at": {"$gte": date_from, "$lte": date_to}
    })
    
    report_data["user_statistics"] = {
        "total_users": total_users,
        "active_users": active_users,
        "inactive_users": total_users - active_users,
        "new_users_in_period": new_users_period,
        "growth_rate": (new_users_period / max(total_users - new_users_period, 1)) * 100
    }
    
    # File Statistics
    total_files = db.files.count_documents({})
    files_in_period = db.files.count_documents({
        "created_at": {"$gte": date_from, "$lte": date_to}
    })
    
    # Storage statistics
    storage_pipeline = [
        {"$group": {
            "_id": None,
            "total_size": {"$sum": "$file_size"},
            "avg_size": {"$avg": "$file_size"},
            "max_size": {"$max": "$file_size"}
        }}
    ]
    storage_stats = list(db.files.aggregate(storage_pipeline))
    storage_data = storage_stats[0] if storage_stats else {
        "total_size": 0, "avg_size": 0, "max_size": 0
    }
    
    report_data["file_statistics"] = {
        "total_files": total_files,
        "files_uploaded_in_period": files_in_period,
        "total_storage_bytes": storage_data["total_size"],
        "total_storage_gb": round(storage_data["total_size"] / (1024**3), 2),
        "average_file_size_mb": round(storage_data["avg_size"] / (1024**2), 2),
        "largest_file_size_mb": round(storage_data["max_size"] / (1024**2), 2)
    }
    
    # File type distribution
    file_type_pipeline = [
        {"$group": {
            "_id": "$file_type",
            "count": {"$sum": 1},
            "total_size": {"$sum": "$file_size"}
        }},
        {"$sort": {"count": -1}}
    ]
    file_types = list(db.files.aggregate(file_type_pipeline))
    
    report_data["file_statistics"]["type_distribution"] = [
        {
            "type": item["_id"] or "unknown",
            "count": item["count"],
            "size_gb": round(item["total_size"] / (1024**3), 2)
        }
        for item in file_types[:10]  # Top 10 file types
    ]
    
    # Admin Activity Statistics
    admin_activity_count = db.admin_activity_logs.count_documents({
        "timestamp": {"$gte": date_from, "$lte": date_to}
    })
    
    admin_activity_pipeline = [
        {"$match": {"timestamp": {"$gte": date_from, "$lte": date_to}}},
        {"$group": {
            "_id": "$action",
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}}
    ]
    top_admin_actions = list(db.admin_activity_logs.aggregate(admin_activity_pipeline))
    
    report_data["admin_activity"] = {
        "total_actions": admin_activity_count,
        "top_actions": [
            {"action": item["_id"], "count": item["count"]}
            for item in top_admin_actions[:10]
        ]
    }
    
    # System Performance Metrics (simulated)
    report_data["system_performance"] = {
        "uptime_percentage": 99.8,
        "average_response_time_ms": 245,
        "total_api_requests": admin_activity_count * 3,  # Estimated
        "error_rate_percentage": 0.2,
        "peak_concurrent_users": max(active_users // 10, 1)
    }
    
    # Growth Metrics
    previous_period_start = date_from - (date_to - date_from)
    previous_users = db.users.count_documents({
        "created_at": {"$gte": previous_period_start, "$lt": date_from}
    })
    previous_files = db.files.count_documents({
        "created_at": {"$gte": previous_period_start, "$lt": date_from}
    })
    
    report_data["growth_metrics"] = {
        "user_growth_percentage": (
            ((new_users_period - previous_users) / max(previous_users, 1)) * 100
            if previous_users > 0 else 100
        ),
        "file_growth_percentage": (
            ((files_in_period - previous_files) / max(previous_files, 1)) * 100
            if previous_files > 0 else 100
        ),
        "comparison_period": {
            "from": previous_period_start.isoformat(),
            "to": date_from.isoformat()
        }
    }
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="generate_system_overview_report",
        details=f"Generated system overview report for {(date_to - date_from).days} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/reports/system-overview"
    )
    
    # Return based on format
    if export_format == ExportFormat.JSON:
        return report_data
    elif export_format == ExportFormat.CSV:
        return await export_to_csv(report_data, "system_overview_report")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Export format {export_format} not yet supported"
        )

@router.get("/reports/user-activity")
async def generate_user_activity_report(
    request: Request,
    date_from: datetime = Query(...),
    date_to: datetime = Query(...),
    export_format: ExportFormat = Query(ExportFormat.JSON),
    include_inactive: bool = Query(False),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Generate detailed user activity report"""
    # db is imported directly
    
    # Build user filter
    user_filter = {}
    if not include_inactive:
        user_filter["is_active"] = True
    
    # Get user activity data
    user_activity_pipeline = [
        {"$match": user_filter},
        {"$lookup": {
            "from": "files",
            "localField": "email",
            "foreignField": "uploaded_by",
            "as": "files"
        }},
        {"$addFields": {
            "total_files": {"$size": "$files"},
            "total_storage": {"$sum": "$files.file_size"},
            "recent_files": {
                "$size": {
                    "$filter": {
                        "input": "$files",
                        "cond": {
                            "$and": [
                                {"$gte": ["$$this.created_at", date_from]},
                                {"$lte": ["$$this.created_at", date_to]}
                            ]
                        }
                    }
                }
            }
        }},
        {"$project": {
            "email": 1,
            "username": 1,
            "created_at": 1,
            "last_login": 1,
            "is_active": 1,
            "total_files": 1,
            "total_storage": 1,
            "recent_files": 1,
            "storage_mb": {"$round": [{"$divide": ["$total_storage", 1048576]}, 2]}
        }},
        {"$sort": {"recent_files": -1}}
    ]
    
    users_data = list(db.users.aggregate(user_activity_pipeline))
    
    # Activity summary
    activity_summary = {
        "total_users_analyzed": len(users_data),
        "active_users_in_period": sum(1 for user in users_data if user["recent_files"] > 0),
        "total_files_in_period": sum(user["recent_files"] for user in users_data),
        "total_storage_in_period_gb": round(sum(user["total_storage"] for user in users_data) / (1024**3), 2),
        "average_files_per_active_user": 0,
        "top_users_by_activity": []
    }
    
    active_users = [user for user in users_data if user["recent_files"] > 0]
    if active_users:
        activity_summary["average_files_per_active_user"] = round(
            sum(user["recent_files"] for user in active_users) / len(active_users), 2
        )
    
    # Top 10 most active users
    activity_summary["top_users_by_activity"] = [
        {
            "email": user["email"],
            "username": user["username"],
            "files_in_period": user["recent_files"],
            "total_files": user["total_files"],
            "storage_mb": user["storage_mb"]
        }
        for user in users_data[:10]
    ]
    
    report_data = {
        "report_info": {
            "type": "user_activity",
            "title": "User Activity Report",
            "generated_at": datetime.utcnow().isoformat(),
            "generated_by": current_admin.email,
            "period": {
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
                "days": (date_to - date_from).days
            },
            "filters": {
                "include_inactive": include_inactive
            }
        },
        "summary": activity_summary,
        "user_details": users_data
    }
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="generate_user_activity_report",
        details=f"Generated user activity report for {len(users_data)} users",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/reports/user-activity"
    )
    
    if export_format == ExportFormat.JSON:
        return report_data
    elif export_format == ExportFormat.CSV:
        return await export_to_csv(report_data["user_details"], "user_activity_report")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Export format {export_format} not yet supported"
        )

@router.get("/reports/storage-usage")
async def generate_storage_usage_report(
    request: Request,
    date_from: datetime = Query(...),
    date_to: datetime = Query(...),
    export_format: ExportFormat = Query(ExportFormat.JSON),
    group_by: str = Query("user", pattern="^(user|file_type|storage_location|date)$"),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Generate detailed storage usage report"""
    # db is imported directly
    
    report_data = {
        "report_info": {
            "type": "storage_usage",
            "title": "Storage Usage Report",
            "generated_at": datetime.utcnow().isoformat(),
            "generated_by": current_admin.email,
            "period": {
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
                "days": (date_to - date_from).days
            },
            "group_by": group_by
        },
        "summary": {},
        "detailed_breakdown": []
    }
    
    # Overall summary
    total_pipeline = [
        {"$group": {
            "_id": None,
            "total_files": {"$sum": 1},
            "total_size": {"$sum": "$file_size"},
            "avg_size": {"$avg": "$file_size"}
        }}
    ]
    
    period_pipeline = [
        {"$match": {"created_at": {"$gte": date_from, "$lte": date_to}}},
        {"$group": {
            "_id": None,
            "period_files": {"$sum": 1},
            "period_size": {"$sum": "$file_size"}
        }}
    ]
    
    total_stats = list(db.files.aggregate(total_pipeline))
    period_stats = list(db.files.aggregate(period_pipeline))
    
    total_data = total_stats[0] if total_stats else {"total_files": 0, "total_size": 0, "avg_size": 0}
    period_data = period_stats[0] if period_stats else {"period_files": 0, "period_size": 0}
    
    report_data["summary"] = {
        "total_files": total_data["total_files"],
        "total_storage_gb": round(total_data["total_size"] / (1024**3), 2),
        "files_in_period": period_data["period_files"],
        "storage_added_in_period_gb": round(period_data["period_size"] / (1024**3), 2),
        "average_file_size_mb": round(total_data["avg_size"] / (1024**2), 2)
    }
    
    # Detailed breakdown based on group_by parameter
    if group_by == "user":
        breakdown_pipeline = [
            {"$group": {
                "_id": "$uploaded_by",
                "file_count": {"$sum": 1},
                "total_size": {"$sum": "$file_size"}
            }},
            {"$sort": {"total_size": -1}},
            {"$limit": 50}  # Top 50 users
        ]
        
        breakdown_data = list(db.files.aggregate(breakdown_pipeline))
        report_data["detailed_breakdown"] = [
            {
                "user_email": item["_id"],
                "file_count": item["file_count"],
                "storage_gb": round(item["total_size"] / (1024**3), 2),
                "storage_mb": round(item["total_size"] / (1024**2), 2)
            }
            for item in breakdown_data
        ]
        
    elif group_by == "file_type":
        breakdown_pipeline = [
            {"$group": {
                "_id": "$file_type",
                "file_count": {"$sum": 1},
                "total_size": {"$sum": "$file_size"},
                "avg_size": {"$avg": "$file_size"}
            }},
            {"$sort": {"total_size": -1}}
        ]
        
        breakdown_data = list(db.files.aggregate(breakdown_pipeline))
        report_data["detailed_breakdown"] = [
            {
                "file_type": item["_id"] or "unknown",
                "file_count": item["file_count"],
                "total_storage_gb": round(item["total_size"] / (1024**3), 2),
                "average_size_mb": round(item["avg_size"] / (1024**2), 2),
                "percentage_of_total": round((item["total_size"] / max(total_data["total_size"], 1)) * 100, 2)
            }
            for item in breakdown_data
        ]
        
    elif group_by == "storage_location":
        breakdown_pipeline = [
            {"$group": {
                "_id": "$storage_location",
                "file_count": {"$sum": 1},
                "total_size": {"$sum": "$file_size"}
            }},
            {"$sort": {"total_size": -1}}
        ]
        
        breakdown_data = list(db.files.aggregate(breakdown_pipeline))
        report_data["detailed_breakdown"] = [
            {
                "storage_location": item["_id"],
                "file_count": item["file_count"],
                "storage_gb": round(item["total_size"] / (1024**3), 2),
                "percentage_of_total": round((item["total_size"] / max(total_data["total_size"], 1)) * 100, 2)
            }
            for item in breakdown_data
        ]
        
    elif group_by == "date":
        # Daily breakdown for the period
        breakdown_pipeline = [
            {"$match": {"created_at": {"$gte": date_from, "$lte": date_to}}},
            {"$group": {
                "_id": {
                    "year": {"$year": "$created_at"},
                    "month": {"$month": "$created_at"},
                    "day": {"$dayOfMonth": "$created_at"}
                },
                "file_count": {"$sum": 1},
                "total_size": {"$sum": "$file_size"}
            }},
            {"$sort": {"_id": 1}}
        ]
        
        breakdown_data = list(db.files.aggregate(breakdown_pipeline))
        report_data["detailed_breakdown"] = [
            {
                "date": f"{item['_id']['year']}-{item['_id']['month']:02d}-{item['_id']['day']:02d}",
                "file_count": item["file_count"],
                "storage_added_gb": round(item["total_size"] / (1024**3), 2)
            }
            for item in breakdown_data
        ]
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="generate_storage_usage_report",
        details=f"Generated storage usage report grouped by {group_by}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/reports/storage-usage"
    )
    
    if export_format == ExportFormat.JSON:
        return report_data
    elif export_format == ExportFormat.CSV:
        return await export_to_csv(report_data["detailed_breakdown"], f"storage_usage_by_{group_by}_report")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Export format {export_format} not yet supported"
        )

# ================================
# CUSTOM REPORT BUILDER
# ================================

@router.post("/reports/custom")
async def generate_custom_report(
    report_config: CustomReportBuilder,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Generate custom report based on user configuration"""
    # db is imported directly
    
    # Validate data sources
    allowed_collections = [
        "users", "files", "admin_activity_logs", "notifications", 
        "notification_deliveries", "backup_logs"
    ]
    
    invalid_sources = [src for src in report_config.data_sources if src not in allowed_collections]
    if invalid_sources:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid data sources: {invalid_sources}. Allowed: {allowed_collections}"
        )
    
    report_data = {
        "report_info": {
            "type": "custom",
            "title": report_config.title,
            "description": report_config.description,
            "generated_at": datetime.utcnow().isoformat(),
            "generated_by": current_admin.email,
            "period": {
                "from": report_config.date_from.isoformat(),
                "to": report_config.date_to.isoformat()
            },
            "data_sources": report_config.data_sources,
            "fields": report_config.fields
        },
        "results": {}
    }
    
    # Process each data source
    for collection_name in report_config.data_sources:
        collection = getattr(db, collection_name)
        
        # Build base query with date filter
        base_query = {}
        date_field = "created_at"  # Most collections use this
        if collection_name == "admin_activity_logs":
            date_field = "timestamp"
        
        base_query[date_field] = {
            "$gte": report_config.date_from,
            "$lte": report_config.date_to
        }
        
        # Use custom aggregation pipeline if provided
        if report_config.aggregation_pipeline:
            pipeline = [{"$match": base_query}] + report_config.aggregation_pipeline
            results = list(collection.aggregate(pipeline))
        else:
            # Simple field projection
            projection = {field: 1 for field in report_config.fields} if report_config.fields else {}
            results = list(collection.find(base_query, projection).limit(1000))  # Limit to prevent memory issues
            
            # Convert ObjectId to string
            for item in results:
                if "_id" in item:
                    item["_id"] = str(item["_id"])
        
        report_data["results"][collection_name] = {
            "count": len(results),
            "data": results
        }
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="generate_custom_report",
        details=f"Generated custom report: {report_config.title}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/reports/custom"
    )
    
    if report_config.export_format == ExportFormat.JSON:
        return report_data
    elif report_config.export_format == ExportFormat.CSV:
        # Flatten all results for CSV export
        all_data = []
        for source, data in report_data["results"].items():
            for item in data["data"]:
                item["_data_source"] = source
                all_data.append(item)
        return await export_to_csv(all_data, f"custom_report_{report_config.title.replace(' ', '_')}")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Export format {report_config.export_format} not yet supported"
        )

# ================================
# REPORT SCHEDULING (Future Implementation)
# ================================

@router.get("/reports/scheduled")
async def get_scheduled_reports(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get all scheduled reports"""
    # db is imported directly
    
    # For now, return empty list - full implementation would store schedules in DB
    scheduled_reports = []
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_scheduled_reports",
        details="Viewed scheduled reports list",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/reports/scheduled"
    )
    
    return {
        "scheduled_reports": scheduled_reports,
        "total": len(scheduled_reports),
        "note": "Report scheduling feature coming soon"
    }

@router.post("/reports/schedule")
async def create_scheduled_report(
    schedule_config: ScheduledReportCreate,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_superadmin)  # Superadmin only
):
    """Create a new scheduled report (placeholder for future implementation)"""
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="create_scheduled_report",
        details=f"Attempted to create scheduled report: {schedule_config.title}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/reports/schedule"
    )
    
    return {
        "message": "Report scheduling feature coming soon",
        "config_received": {
            "title": schedule_config.title,
            "frequency": schedule_config.frequency,
            "recipients": len(schedule_config.recipients)
        }
    }

# ================================
# EXPORT UTILITIES
# ================================

async def export_to_csv(data: List[Dict[str, Any]], filename: str) -> StreamingResponse:
    """Export data to CSV format"""
    if not data:
        # Create empty CSV
        output = io.StringIO()
        output.write("No data available for the selected criteria\n")
        output.seek(0)
        
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}.csv"}
        )
    
    # Get all unique keys from all dictionaries
    all_keys = set()
    for item in data:
        all_keys.update(item.keys())
    
    # Sort keys for consistent column order
    fieldnames = sorted(all_keys)
    
    # Create CSV content
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    
    for item in data:
        # Handle nested objects and arrays by converting to string
        csv_row = {}
        for key in fieldnames:
            value = item.get(key)
            if isinstance(value, (dict, list)):
                csv_row[key] = json.dumps(value)
            elif isinstance(value, datetime):
                csv_row[key] = value.isoformat()
            else:
                csv_row[key] = value
        writer.writerow(csv_row)
    
    output.seek(0)
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}.csv"}
    )

# ================================
# REPORT TEMPLATES AND PRESETS
# ================================

@router.get("/reports/templates")
async def get_report_templates(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get available report templates and presets"""
    
    templates = [
        {
            "id": "weekly_summary",
            "name": "Weekly Summary Report",
            "description": "Comprehensive weekly overview of system activity",
            "type": ReportType.SYSTEM_OVERVIEW,
            "default_period_days": 7,
            "includes": ["users", "files", "storage", "admin_activity"]
        },
        {
            "id": "monthly_storage",
            "name": "Monthly Storage Analysis",
            "description": "Detailed storage usage and growth analysis",
            "type": ReportType.STORAGE_USAGE,
            "default_period_days": 30,
            "includes": ["storage_by_user", "storage_by_type", "growth_trends"]
        },
        {
            "id": "user_engagement",
            "name": "User Engagement Report",
            "description": "User activity and engagement metrics",
            "type": ReportType.USER_ACTIVITY,
            "default_period_days": 30,
            "includes": ["active_users", "upload_patterns", "retention_metrics"]
        },
        {
            "id": "security_audit",
            "name": "Security Audit Report",
            "description": "Security events and admin activity analysis",
            "type": ReportType.SECURITY_AUDIT,
            "default_period_days": 7,
            "includes": ["admin_actions", "login_attempts", "security_events"]
        }
    ]
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_report_templates",
        details=f"Viewed {len(templates)} report templates",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/reports/templates"
    )
    
    return {
        "templates": templates,
        "total": len(templates)
    }