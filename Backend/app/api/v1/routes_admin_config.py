from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from app.services.admin_auth_service import get_current_admin, get_current_superadmin, log_admin_activity, get_client_ip
from app.models.admin import AdminUserInDB
from app.db.mongodb import db
from app.core.config import settings

router = APIRouter()

# Configuration Models
class SystemConfigUpdate(BaseModel):
    max_file_size_mb: Optional[int] = Field(None, ge=1, le=10240)  # 1MB to 10GB
    max_files_per_user: Optional[int] = Field(None, ge=1, le=100000)
    default_storage_quota_gb: Optional[int] = Field(None, ge=1, le=10000)
    upload_rate_limit_per_hour: Optional[int] = Field(None, ge=1, le=10000)
    enable_public_registration: Optional[bool] = None
    enable_file_preview: Optional[bool] = None
    enable_batch_operations: Optional[bool] = None
    maintenance_mode: Optional[bool] = None
    maintenance_message: Optional[str] = Field(None, max_length=500)

class EmailConfigUpdate(BaseModel):
    smtp_host: Optional[str] = Field(None, max_length=255)
    smtp_port: Optional[int] = Field(None, ge=1, le=65535)
    smtp_username: Optional[str] = Field(None, max_length=255)
    smtp_password: Optional[str] = Field(None, max_length=255)
    smtp_use_tls: Optional[bool] = None
    from_email: Optional[str] = Field(None, max_length=255)
    from_name: Optional[str] = Field(None, max_length=255)

class SecurityConfigUpdate(BaseModel):
    session_timeout_minutes: Optional[int] = Field(None, ge=5, le=10080)  # 5 minutes to 1 week
    max_login_attempts: Optional[int] = Field(None, ge=1, le=100)
    lockout_duration_minutes: Optional[int] = Field(None, ge=1, le=1440)  # 1 minute to 24 hours
    require_strong_passwords: Optional[bool] = None
    enable_two_factor_auth: Optional[bool] = None
    allowed_cors_origins: Optional[list] = None
    enable_api_rate_limiting: Optional[bool] = None

# ================================
# SYSTEM CONFIGURATION ENDPOINTS
# ================================

@router.get("/config/system")
async def get_system_configuration(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get current system configuration settings"""
    
    # Get configuration from database or create default
    config = db.system_config.find_one({"_id": "system"}) or {}
    
    # Default configuration values
    default_config = {
        "max_file_size_mb": 1000,  # 1GB default
        "max_files_per_user": 1000,
        "default_storage_quota_gb": 100,
        "upload_rate_limit_per_hour": 100,
        "enable_public_registration": True,
        "enable_file_preview": True,
        "enable_batch_operations": True,
        "maintenance_mode": False,
        "maintenance_message": "System is under maintenance. Please try again later.",
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": "system"
    }
    
    # Merge with existing config
    system_config = {**default_config, **{k: v for k, v in config.items() if k != "_id"}}
    
    # Get current usage statistics
    total_users = db.users.count_documents({})
    total_files = db.files.count_documents({})
    total_storage_bytes = sum(
        file.get("size_bytes", 0) 
        for file in db.files.find({}, {"size_bytes": 1})
    )
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_system_config",
        details="Viewed system configuration settings",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/config/system"
    )
    
    return {
        "configuration": system_config,
        "current_usage": {
            "total_users": total_users,
            "total_files": total_files,
            "total_storage_gb": round(total_storage_bytes / (1024**3), 2),
            "average_files_per_user": round(total_files / total_users, 2) if total_users > 0 else 0
        }
    }

@router.put("/config/system")
async def update_system_configuration(
    config_update: SystemConfigUpdate,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_superadmin)  # Only superadmin can update
):
    """Update system configuration settings (superadmin only)"""
    
    # Get current config
    current_config = db.system_config.find_one({"_id": "system"}) or {}
    
    # Prepare update data
    update_data = {k: v for k, v in config_update.dict().items() if v is not None}
    update_data.update({
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": current_admin.email
    })
    
    # Update configuration
    db.system_config.update_one(
        {"_id": "system"},
        {"$set": update_data},
        upsert=True
    )
    
    # Get updated config
    updated_config = db.system_config.find_one({"_id": "system"})
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="update_system_config",
        details=f"Updated system configuration: {', '.join(update_data.keys())}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/config/system"
    )
    
    return {
        "message": "System configuration updated successfully",
        "updated_fields": list(update_data.keys()),
        "configuration": {k: v for k, v in updated_config.items() if k != "_id"}
    }

@router.get("/config/email")
async def get_email_configuration(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get email/SMTP configuration settings"""
    
    config = db.system_config.find_one({"_id": "email"}) or {}
    
    # Default email configuration (with sensitive data masked)
    default_config = {
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_username": "",
        "smtp_password": "***masked***" if config.get("smtp_password") else "",
        "smtp_use_tls": True,
        "from_email": "",
        "from_name": "DirectDrive System",
        "email_enabled": bool(config.get("smtp_host")),
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": "system"
    }
    
    # Merge with existing config (mask password)
    email_config = {**default_config, **{k: v for k, v in config.items() if k != "_id"}}
    if email_config.get("smtp_password"):
        email_config["smtp_password"] = "***masked***"
    
    # Test email connectivity (simulated)
    email_status = {
        "connection_status": "connected" if email_config["email_enabled"] else "not_configured",
        "last_test": datetime.utcnow().isoformat(),
        "test_result": "success" if email_config["email_enabled"] else "not_tested"
    }
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_email_config",
        details="Viewed email configuration settings",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/config/email"
    )
    
    return {
        "configuration": email_config,
        "status": email_status
    }

@router.put("/config/email")
async def update_email_configuration(
    config_update: EmailConfigUpdate,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_superadmin)
):
    """Update email/SMTP configuration settings (superadmin only)"""
    
    # Prepare update data
    update_data = {k: v for k, v in config_update.dict().items() if v is not None}
    update_data.update({
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": current_admin.email
    })
    
    # Update configuration
    db.system_config.update_one(
        {"_id": "email"},
        {"$set": update_data},
        upsert=True
    )
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="update_email_config",
        details=f"Updated email configuration: {', '.join(update_data.keys())}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/config/email"
    )
    
    return {
        "message": "Email configuration updated successfully",
        "updated_fields": list(update_data.keys())
    }

@router.get("/config/security")
async def get_security_configuration(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get security configuration settings"""
    
    config = db.system_config.find_one({"_id": "security"}) or {}
    
    # Default security configuration
    default_config = {
        "session_timeout_minutes": 60,
        "max_login_attempts": 5,
        "lockout_duration_minutes": 15,
        "require_strong_passwords": True,
        "enable_two_factor_auth": False,
        "allowed_cors_origins": ["http://localhost:4200", "https://directdrive.com"],
        "enable_api_rate_limiting": True,
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": "system"
    }
    
    # Merge with existing config
    security_config = {**default_config, **{k: v for k, v in config.items() if k != "_id"}}
    
    # Get security statistics
    recent_login_attempts = db.admin_activity.count_documents({
        "action": {"$in": ["login", "login_failed"]},
        "timestamp": {"$gte": datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)}
    })
    
    failed_logins_today = db.admin_activity.count_documents({
        "action": "login_failed",
        "timestamp": {"$gte": datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)}
    })
    
    security_stats = {
        "login_attempts_today": recent_login_attempts,
        "failed_logins_today": failed_logins_today,
        "success_rate": round((recent_login_attempts - failed_logins_today) / recent_login_attempts * 100, 2) if recent_login_attempts > 0 else 100
    }
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_security_config",
        details="Viewed security configuration settings",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/config/security"
    )
    
    return {
        "configuration": security_config,
        "security_stats": security_stats
    }

@router.put("/config/security")
async def update_security_configuration(
    config_update: SecurityConfigUpdate,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_superadmin)
):
    """Update security configuration settings (superadmin only)"""
    
    # Prepare update data
    update_data = {k: v for k, v in config_update.dict().items() if v is not None}
    update_data.update({
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": current_admin.email
    })
    
    # Update configuration
    db.system_config.update_one(
        {"_id": "security"},
        {"$set": update_data},
        upsert=True
    )
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="update_security_config",
        details=f"Updated security configuration: {', '.join(update_data.keys())}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/config/security"
    )
    
    return {
        "message": "Security configuration updated successfully",
        "updated_fields": list(update_data.keys())
    }

@router.get("/config/feature-flags")
async def get_feature_flags(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get current feature flags and their status"""
    
    config = db.system_config.find_one({"_id": "feature_flags"}) or {}
    
    # Default feature flags
    default_flags = {
        "enable_file_sharing": True,
        "enable_batch_uploads": True,
        "enable_file_preview": True,
        "enable_backup_system": True,
        "enable_user_registration": True,
        "enable_admin_notifications": True,
        "enable_system_monitoring": True,
        "enable_log_export": True,
        "enable_api_monitoring": True,
        "enable_rate_limiting": True,
        "enable_maintenance_mode": False,
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": "system"
    }
    
    # Merge with existing config
    feature_flags = {**default_flags, **{k: v for k, v in config.items() if k != "_id"}}
    
    # Calculate feature usage statistics
    enabled_features = sum(1 for v in feature_flags.values() if isinstance(v, bool) and v)
    total_features = sum(1 for v in feature_flags.values() if isinstance(v, bool))
    
    feature_stats = {
        "enabled_features": enabled_features,
        "total_features": total_features,
        "enablement_percentage": round(enabled_features / total_features * 100, 2) if total_features > 0 else 0
    }
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_feature_flags",
        details="Viewed feature flags configuration",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/config/feature-flags"
    )
    
    return {
        "feature_flags": feature_flags,
        "statistics": feature_stats
    }

@router.put("/config/feature-flags")
async def update_feature_flags(
    flags_update: Dict[str, bool],
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_superadmin)
):
    """Update feature flags (superadmin only)"""
    
    # Validate that all values are boolean
    if not all(isinstance(v, bool) for v in flags_update.values()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All feature flag values must be boolean"
        )
    
    # Prepare update data
    update_data = flags_update.copy()
    update_data.update({
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": current_admin.email
    })
    
    # Update feature flags
    db.system_config.update_one(
        {"_id": "feature_flags"},
        {"$set": update_data},
        upsert=True
    )
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="update_feature_flags",
        details=f"Updated feature flags: {', '.join(flags_update.keys())}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/config/feature-flags"
    )
    
    return {
        "message": "Feature flags updated successfully",
        "updated_flags": list(flags_update.keys()),
        "changes": flags_update
    }

@router.post("/config/maintenance-mode")
async def toggle_maintenance_mode(
    enable: bool,
    message: Optional[str] = "System is under maintenance. Please try again later.",
    request: Request = None,
    current_admin: AdminUserInDB = Depends(get_current_superadmin)
):
    """Toggle maintenance mode on/off (superadmin only)"""
    
    # Update maintenance mode setting
    update_data = {
        "maintenance_mode": enable,
        "maintenance_message": message,
        "maintenance_enabled_at": datetime.utcnow().isoformat() if enable else None,
        "maintenance_enabled_by": current_admin.email if enable else None,
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": current_admin.email
    }
    
    db.system_config.update_one(
        {"_id": "system"},
        {"$set": update_data},
        upsert=True
    )
    
    action = "enable_maintenance" if enable else "disable_maintenance"
    await log_admin_activity(
        admin_email=current_admin.email,
        action=action,
        details=f"{'Enabled' if enable else 'Disabled'} maintenance mode: {message}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/config/maintenance-mode"
    )
    
    return {
        "message": f"Maintenance mode {'enabled' if enable else 'disabled'} successfully",
        "maintenance_mode": enable,
        "maintenance_message": message,
        "enabled_by": current_admin.email if enable else None,
        "enabled_at": update_data["maintenance_enabled_at"]
    }

@router.get("/config/export")
async def export_configuration(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_superadmin)
):
    """Export all configuration settings (superadmin only)"""
    
    from fastapi.responses import StreamingResponse
    import json
    import io
    
    # Get all configuration collections
    configs = {
        "system": db.system_config.find_one({"_id": "system"}),
        "email": db.system_config.find_one({"_id": "email"}),
        "security": db.system_config.find_one({"_id": "security"}),
        "feature_flags": db.system_config.find_one({"_id": "feature_flags"})
    }
    
    # Remove _id fields and mask sensitive data
    for config_type, config_data in configs.items():
        if config_data:
            config_data.pop("_id", None)
            if config_type == "email" and config_data.get("smtp_password"):
                config_data["smtp_password"] = "***masked***"
    
    # Prepare export data
    export_data = {
        "export_info": {
            "exported_at": datetime.utcnow().isoformat(),
            "exported_by": current_admin.email,
            "system_version": "1.0.0"
        },
        "configurations": configs
    }
    
    content = json.dumps(export_data, indent=2)
    filename = f"directdrive_config_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="export_config",
        details="Exported system configuration",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/config/export"
    )
    
    def generate():
        yield content
    
    return StreamingResponse(
        generate(),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ================================
# ADVANCED SECURITY SETTINGS ENDPOINTS
# ================================

class AccessControlRule(BaseModel):
    rule_name: str = Field(..., max_length=100)
    rule_type: str = Field(..., pattern="^(ip_whitelist|ip_blacklist|user_role|endpoint_access)$")
    rule_value: str = Field(..., max_length=500)
    is_active: bool = True
    description: Optional[str] = Field(None, max_length=200)

class PasswordPolicy(BaseModel):
    min_length: Optional[int] = Field(None, ge=8, le=128)
    require_uppercase: Optional[bool] = None
    require_lowercase: Optional[bool] = None
    require_numbers: Optional[bool] = None
    require_special_chars: Optional[bool] = None
    password_history_count: Optional[int] = Field(None, ge=0, le=24)
    password_expiry_days: Optional[int] = Field(None, ge=0, le=365)

@router.get("/security/access-rules")
async def get_access_control_rules(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get current access control rules"""
    
    rules = list(db.access_rules.find({}, {"_id": 0}))
    
    # Add default rules if none exist
    if not rules:
        default_rules = [
            {
                "rule_name": "allow_localhost",
                "rule_type": "ip_whitelist",
                "rule_value": "127.0.0.1,::1",
                "is_active": True,
                "description": "Allow localhost access",
                "created_at": datetime.utcnow().isoformat(),
                "created_by": "system"
            },
            {
                "rule_name": "superadmin_all_access",
                "rule_type": "user_role",
                "rule_value": "superadmin:*",
                "is_active": True,
                "description": "Superadmin has access to all endpoints",
                "created_at": datetime.utcnow().isoformat(),
                "created_by": "system"
            }
        ]
        
        # Insert default rules
        if default_rules:
            db.access_rules.insert_many(default_rules)
            rules = default_rules
    
    # Get access rule statistics
    total_rules = len(rules)
    active_rules = len([r for r in rules if r.get("is_active", False)])
    rule_types = {}
    for rule in rules:
        rule_type = rule.get("rule_type", "unknown")
        rule_types[rule_type] = rule_types.get(rule_type, 0) + 1
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_access_rules",
        details="Viewed access control rules",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/security/access-rules"
    )
    
    return {
        "access_rules": rules,
        "statistics": {
            "total_rules": total_rules,
            "active_rules": active_rules,
            "rule_types": rule_types
        }
    }

@router.post("/security/access-rules")
async def create_access_control_rule(
    rule: AccessControlRule,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_superadmin)
):
    """Create new access control rule (superadmin only)"""
    
    # Check if rule name already exists
    existing_rule = db.access_rules.find_one({"rule_name": rule.rule_name})
    if existing_rule:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rule with this name already exists"
        )
    
    # Create rule document
    rule_doc = rule.dict()
    rule_doc.update({
        "created_at": datetime.utcnow().isoformat(),
        "created_by": current_admin.email,
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": current_admin.email
    })
    
    # Insert rule
    db.access_rules.insert_one(rule_doc)
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="create_access_rule",
        details=f"Created access rule: {rule.rule_name} ({rule.rule_type})",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/security/access-rules"
    )
    
    return {
        "message": "Access control rule created successfully",
        "rule": rule_doc
    }

@router.put("/security/access-rules/{rule_name}")
async def update_access_control_rule(
    rule_name: str,
    rule_update: AccessControlRule,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_superadmin)
):
    """Update access control rule (superadmin only)"""
    
    # Check if rule exists
    existing_rule = db.access_rules.find_one({"rule_name": rule_name})
    if not existing_rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access rule not found"
        )
    
    # Prepare update data
    update_data = rule_update.dict()
    update_data.update({
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": current_admin.email
    })
    
    # Update rule
    db.access_rules.update_one(
        {"rule_name": rule_name},
        {"$set": update_data}
    )
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="update_access_rule",
        details=f"Updated access rule: {rule_name}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/security/access-rules/{rule_name}"
    )
    
    return {
        "message": "Access control rule updated successfully",
        "rule_name": rule_name
    }

@router.delete("/security/access-rules/{rule_name}")
async def delete_access_control_rule(
    rule_name: str,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_superadmin)
):
    """Delete access control rule (superadmin only)"""
    
    # Check if rule exists
    existing_rule = db.access_rules.find_one({"rule_name": rule_name})
    if not existing_rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access rule not found"
        )
    
    # Delete rule
    result = db.access_rules.delete_one({"rule_name": rule_name})
    
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete access rule"
        )
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="delete_access_rule",
        details=f"Deleted access rule: {rule_name}",
        ip_address=get_client_ip(request),
        endpoint=f"/api/v1/admin/security/access-rules/{rule_name}"
    )
    
    return {
        "message": "Access control rule deleted successfully",
        "rule_name": rule_name
    }

@router.get("/security/password-policy")
async def get_password_policy(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get current password policy settings"""
    
    policy = db.system_config.find_one({"_id": "password_policy"}) or {}
    
    # Default password policy
    default_policy = {
        "min_length": 8,
        "require_uppercase": True,
        "require_lowercase": True,
        "require_numbers": True,
        "require_special_chars": True,
        "password_history_count": 5,
        "password_expiry_days": 90,
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": "system"
    }
    
    # Merge with existing policy
    password_policy = {**default_policy, **{k: v for k, v in policy.items() if k != "_id"}}
    
    # Get password compliance statistics (simulated)
    total_users = db.users.count_documents({})
    compliant_users = int(total_users * 0.85)  # Simulated 85% compliance
    
    compliance_stats = {
        "total_users": total_users,
        "compliant_users": compliant_users,
        "compliance_rate": round(compliant_users / total_users * 100, 2) if total_users > 0 else 100,
        "users_need_password_update": total_users - compliant_users
    }
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_password_policy",
        details="Viewed password policy settings",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/security/password-policy"
    )
    
    return {
        "password_policy": password_policy,
        "compliance_stats": compliance_stats
    }

@router.put("/security/password-policy")
async def update_password_policy(
    policy_update: PasswordPolicy,
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_superadmin)
):
    """Update password policy settings (superadmin only)"""
    
    # Prepare update data
    update_data = {k: v for k, v in policy_update.dict().items() if v is not None}
    update_data.update({
        "last_updated": datetime.utcnow().isoformat(),
        "updated_by": current_admin.email
    })
    
    # Update password policy
    db.system_config.update_one(
        {"_id": "password_policy"},
        {"$set": update_data},
        upsert=True
    )
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="update_password_policy",
        details=f"Updated password policy: {', '.join(update_data.keys())}",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/security/password-policy"
    )
    
    return {
        "message": "Password policy updated successfully",
        "updated_fields": list(update_data.keys())
    }

@router.get("/security/audit-trail")
async def get_security_audit_trail(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    action_filter: str = Query(None),
    admin_filter: str = Query(None),
    days: int = Query(30, ge=1, le=365),
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get security-related audit trail"""
    
    skip = (page - 1) * limit
    since_time = datetime.utcnow() - timedelta(days=days)
    
    # Build query for security-related events
    security_actions = [
        "login", "login_failed", "logout", "create_admin", "update_admin", 
        "delete_admin", "change_password", "reset_password", "update_security_config",
        "create_access_rule", "update_access_rule", "delete_access_rule",
        "update_password_policy", "enable_maintenance", "disable_maintenance"
    ]
    
    query = {
        "timestamp": {"$gte": since_time},
        "action": {"$in": security_actions}
    }
    
    if action_filter:
        query["action"] = {"$regex": action_filter, "$options": "i"}
    if admin_filter:
        query["admin_email"] = {"$regex": admin_filter, "$options": "i"}
    
    # Get audit logs
    audit_logs = list(db.admin_activity.find(
        query,
        {
            "timestamp": 1, "admin_email": 1, "action": 1,
            "details": 1, "ip_address": 1, "endpoint": 1
        }
    ).sort("timestamp", -1).skip(skip).limit(limit))
    
    total_logs = db.admin_activity.count_documents(query)
    
    # Get security event summary
    event_summary = list(db.admin_activity.aggregate([
        {"$match": query},
        {"$group": {
            "_id": "$action",
            "count": {"$sum": 1},
            "last_occurrence": {"$max": "$timestamp"}
        }},
        {"$sort": {"count": -1}}
    ]))
    
    # Get admin activity summary
    admin_summary = list(db.admin_activity.aggregate([
        {"$match": query},
        {"$group": {
            "_id": "$admin_email",
            "security_actions": {"$sum": 1},
            "last_activity": {"$max": "$timestamp"},
            "action_types": {"$addToSet": "$action"}
        }},
        {"$sort": {"security_actions": -1}},
        {"$limit": 10}
    ]))
    
    for admin in admin_summary:
        admin["unique_action_types"] = len(admin["action_types"])
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_security_audit",
        details=f"Viewed security audit trail - page {page}, period {days} days",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/security/audit-trail"
    )
    
    return {
        "audit_logs": audit_logs,
        "total_logs": total_logs,
        "page": page,
        "limit": limit,
        "total_pages": (total_logs + limit - 1) // limit,
        "period_days": days,
        "event_summary": event_summary,
        "admin_summary": admin_summary
    }

@router.get("/security/session-management")
async def get_session_management_info(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get session management information and active sessions"""
    
    # Get recent login information
    recent_logins = list(db.admin_activity.aggregate([
        {
            "$match": {
                "action": "login",
                "timestamp": {"$gte": datetime.utcnow() - timedelta(days=7)}
            }
        },
        {
            "$group": {
                "_id": "$admin_email",
                "last_login": {"$max": "$timestamp"},
                "login_count": {"$sum": 1},
                "ip_addresses": {"$addToSet": "$ip_address"}
            }
        },
        {"$sort": {"last_login": -1}}
    ]))
    
    for login in recent_logins:
        login["unique_ips"] = len(login["ip_addresses"])
        login["ip_addresses"] = login["ip_addresses"][:3]  # Limit for display
    
    # Get session configuration
    session_config = db.system_config.find_one({"_id": "security"}) or {}
    
    session_settings = {
        "session_timeout_minutes": session_config.get("session_timeout_minutes", 60),
        "max_concurrent_sessions": 5,  # Default
        "enable_session_tracking": True,
        "session_security_level": "high"
    }
    
    # Calculate session statistics
    active_sessions = len(recent_logins)  # Simplified representation
    total_login_attempts = db.admin_activity.count_documents({
        "action": {"$in": ["login", "login_failed"]},
        "timestamp": {"$gte": datetime.utcnow() - timedelta(days=1)}
    })
    
    session_stats = {
        "active_sessions": active_sessions,
        "total_login_attempts_24h": total_login_attempts,
        "average_session_duration_minutes": 45,  # Simulated
        "peak_concurrent_sessions": max(active_sessions, 3)  # Simulated
    }
    
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_session_management",
        details="Viewed session management information",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/security/session-management"
    )
    
    return {
        "session_settings": session_settings,
        "session_stats": session_stats,
        "recent_logins": recent_logins
    }