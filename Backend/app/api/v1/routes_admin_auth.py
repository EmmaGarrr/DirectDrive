from fastapi import APIRouter, Depends, HTTPException, status, Request
from datetime import timedelta
from app.services.admin_auth_service import (
    authenticate_admin, 
    create_admin_access_token, 
    get_current_admin, 
    get_current_superadmin,
    create_admin_user,
    log_admin_activity,
    get_admin_activity_logs,
    get_client_ip
)
from app.models.admin import (
    AdminLoginRequest, 
    AdminToken, 
    AdminUserCreate, 
    AdminUserInDB,
    AdminCreateResponse,
    AdminProfileResponse,
    AdminActivityLogResponse
)
from app.core.config import settings

router = APIRouter()

@router.post("/token", response_model=AdminToken)
async def admin_login(request: Request, login_data: AdminLoginRequest):
    """Admin login endpoint"""
    admin = await authenticate_admin(login_data.email, login_data.password)
    if not admin:
        # Log failed login attempt
        await log_admin_activity(
            admin_email=login_data.email,
            action="login_failed",
            details="Invalid admin credentials",
            ip_address=get_client_ip(request),
            endpoint="/api/v1/admin/auth/token"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials or insufficient permissions",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create admin access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_admin_access_token(
        data={"sub": admin.email, "role": admin.role.value}, 
        expires_delta=access_token_expires
    )
    
    # Log successful login
    await log_admin_activity(
        admin_email=admin.email,
        action="login",
        details="Admin login successful",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/auth/token"
    )
    
    return AdminToken(
        access_token=access_token,
        token_type="bearer",
        admin_role=admin.role.value,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

@router.post("/create-admin", response_model=AdminCreateResponse)
async def create_new_admin(
    request: Request,
    admin_data: AdminUserCreate,
    current_superadmin: AdminUserInDB = Depends(get_current_superadmin)
):
    """Create new admin user (superadmin only)"""
    try:
        new_admin = await create_admin_user(admin_data, current_superadmin.email)
        
        # Log admin creation
        await log_admin_activity(
            admin_email=current_superadmin.email,
            action="create_admin",
            details=f"Created admin user: {admin_data.email} with role: {admin_data.role.value}",
            ip_address=get_client_ip(request),
            endpoint="/api/v1/admin/auth/create-admin"
        )
        
        return AdminCreateResponse(
            data=new_admin,
            message="Admin user created successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create admin user: {str(e)}"
        )

@router.get("/me", response_model=AdminProfileResponse)
async def get_admin_profile(
    request: Request,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get current admin profile"""
    # Log profile access
    await log_admin_activity(
        admin_email=current_admin.email,
        action="view_profile",
        details="Admin viewed own profile",
        ip_address=get_client_ip(request),
        endpoint="/api/v1/admin/auth/me"
    )
    
    return AdminProfileResponse(
        data=current_admin,
        message="Admin profile retrieved successfully"
    )

@router.get("/activity-logs", response_model=AdminActivityLogResponse)
async def get_activity_logs(
    request: Request,
    limit: int = 50,
    skip: int = 0,
    current_admin: AdminUserInDB = Depends(get_current_admin)
):
    """Get admin activity logs (admin and superadmin only)"""
    try:
        logs_data = await get_admin_activity_logs(limit=limit, skip=skip)
        
        # Log activity log access
        await log_admin_activity(
            admin_email=current_admin.email,
            action="view_activity_logs",
            details=f"Viewed activity logs (limit: {limit}, skip: {skip})",
            ip_address=get_client_ip(request),
            endpoint="/api/v1/admin/auth/activity-logs"
        )
        
        return AdminActivityLogResponse(
            logs=logs_data["logs"],
            total=logs_data["total"],
            limit=logs_data["limit"],
            skip=logs_data["skip"]
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve activity logs: {str(e)}"
        )

@router.get("/verify-admin")
async def verify_admin_token(current_admin: AdminUserInDB = Depends(get_current_admin)):
    """Verify admin token is valid"""
    return {
        "valid": True,
        "admin_email": current_admin.email,
        "admin_role": current_admin.role.value
    }