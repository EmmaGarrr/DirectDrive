from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum
from .user import UserRole

class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: UserRole = Field(..., description="Admin role: admin or superadmin")

class AdminUserInDB(BaseModel):
    id: str = Field(..., alias="_id")
    email: EmailStr
    role: UserRole
    is_admin: bool = True
    storage_limit_bytes: Optional[int] = None
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    
    class Config:
        populate_by_name = True
        from_attributes = True

class AdminToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin_role: str
    expires_in: int = 86400

class AdminActivityLog(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    admin_email: EmailStr
    action: str
    timestamp: datetime
    ip_address: Optional[str] = None
    endpoint: Optional[str] = None
    details: Optional[str] = None
    
    class Config:
        populate_by_name = True
        from_attributes = True

class AdminActivityLogResponse(BaseModel):
    logs: List[AdminActivityLog]
    total: int
    limit: int
    skip: int

class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str

class AdminProfileResponse(BaseModel):
    data: AdminUserInDB
    message: str

class AdminCreateResponse(BaseModel):
    data: AdminUserInDB
    message: str