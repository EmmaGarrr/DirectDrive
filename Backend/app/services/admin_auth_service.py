from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from app.core.config import settings
from app.db.mongodb import db
from app.models.admin import AdminUserInDB, AdminActivityLog, AdminToken, AdminUserCreate
from app.models.user import UserRole
from app.services.auth_service import verify_password, get_password_hash
import uuid

# Admin-specific OAuth2 scheme
admin_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/admin/auth/token")

def create_admin_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT token with admin-specific claims"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "is_admin": True,
        "iat": datetime.utcnow()
    })
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

async def authenticate_admin(email: str, password: str) -> Optional[AdminUserInDB]:
    """Authenticate admin user and verify admin role"""
    user = db.users.find_one({"email": email})
    if not user:
        return None
    
    # Verify password
    if not verify_password(password, user["hashed_password"]):
        return None
    
    # Verify admin role
    user_role = user.get("role", "regular")
    if user_role not in ["admin", "superadmin"]:
        return None
    
    # Update last login and ensure all required fields exist
    update_fields = {"last_login": datetime.utcnow()}
    
    # Ensure backward compatibility by setting default values for missing fields
    if "role" not in user or user["role"] is None:
        # If no role is set but user was in admin collection, assume admin
        update_fields["role"] = "admin"
        user["role"] = "admin"
        
    if "is_admin" not in user or user["is_admin"] is None:
        update_fields["is_admin"] = True
        user["is_admin"] = True
        
    if "storage_limit_bytes" not in user:
        # Set higher limit for admin users
        admin_storage_limit = 107374182400  # 100GB for admin users
        update_fields["storage_limit_bytes"] = admin_storage_limit
        user["storage_limit_bytes"] = admin_storage_limit
    
    db.users.update_one(
        {"email": email},
        {"$set": update_fields}
    )
    
    return AdminUserInDB(**user)

async def get_current_admin(token: str = Depends(admin_oauth2_scheme)) -> AdminUserInDB:
    """Get current admin user from token with role verification"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired admin token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        email: str = payload.get("sub")
        is_admin: bool = payload.get("is_admin", False)
        
        if email is None or not is_admin:
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception
    
    user = db.users.find_one({"email": email})
    if user is None:
        raise credentials_exception
    
    # Verify admin role still exists
    user_role = user.get("role", "regular")
    if user_role not in ["admin", "superadmin"]:
        raise credentials_exception
    
    # Ensure backward compatibility for missing fields (don't update DB here to avoid performance issues)
    if "is_admin" not in user or user["is_admin"] is None:
        user["is_admin"] = True
        
    if "storage_limit_bytes" not in user:
        user["storage_limit_bytes"] = 107374182400  # 100GB for admin users
    
    return AdminUserInDB(**user)

async def get_current_superadmin(current_admin: AdminUserInDB = Depends(get_current_admin)) -> AdminUserInDB:
    """Verify current user is superadmin"""
    if current_admin.role != UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superadmin can perform this action"
        )
    return current_admin

async def create_admin_user(admin_data: AdminUserCreate, created_by: str) -> AdminUserInDB:
    """Create new admin user (superadmin only)"""
    # Check if admin already exists
    existing_admin = db.users.find_one({"email": admin_data.email})
    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin user with this email already exists"
        )
    
    # Hash password
    hashed_password = get_password_hash(admin_data.password)
    
    # Create admin user document
    admin_dict = {
        "_id": admin_data.email,
        "email": admin_data.email,
        "hashed_password": hashed_password,
        "role": admin_data.role.value,
        "is_admin": True,
        "created_at": datetime.utcnow(),
        "last_login": None
    }
    
    # Insert into database
    db.users.insert_one(admin_dict)
    
    # Log admin creation activity
    await log_admin_activity(
        admin_email=created_by,
        action="create_admin",
        details=f"Created admin user: {admin_data.email} with role: {admin_data.role.value}",
        endpoint="/api/v1/admin/auth/create-admin"
    )
    
    return AdminUserInDB(**admin_dict)

async def log_admin_activity(
    admin_email: str, 
    action: str, 
    details: Optional[str] = None,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None
):
    """Log admin activity to database"""
    log_entry = {
        "_id": str(uuid.uuid4()),
        "admin_email": admin_email,
        "action": action,
        "timestamp": datetime.utcnow(),
        "ip_address": ip_address,
        "endpoint": endpoint,
        "details": details
    }
    
    db.admin_activity_logs.insert_one(log_entry)

async def get_admin_activity_logs(limit: int = 50, skip: int = 0) -> dict:
    """Get paginated admin activity logs"""
    # Get total count
    total = db.admin_activity_logs.count_documents({})
    
    # Get logs with pagination
    logs_cursor = db.admin_activity_logs.find().sort("timestamp", -1).skip(skip).limit(limit)
    logs = [AdminActivityLog(**log) for log in logs_cursor]
    
    return {
        "logs": logs,
        "total": total,
        "limit": limit,
        "skip": skip
    }

def get_client_ip(request: Request) -> str:
    """Extract client IP address from request"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"