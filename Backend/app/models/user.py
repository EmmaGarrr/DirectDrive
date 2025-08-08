from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from enum import Enum

class UserRole(str, Enum):
    REGULAR = "regular"
    ADMIN = "admin" 
    SUPERADMIN = "superadmin"

class UserBase(BaseModel):
    email: EmailStr
    role: Optional[UserRole] = None  # Let database value take precedence
    is_admin: Optional[bool] = None  # Let database value take precedence  
    storage_limit_bytes: Optional[int] = None  # Will be set dynamically

class UserCreate(UserBase):
    password: str

class UserInDB(UserBase):
    id: str = Field(..., alias="_id")
    hashed_password: str

    class Config:
        populate_by_name = True
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class FileTypeBreakdown(BaseModel):
    documents: int = 0  # bytes
    images: int = 0     # bytes  
    videos: int = 0     # bytes
    other: int = 0      # bytes

class UserProfileResponse(UserBase):
    id: str = Field(..., alias="_id")
    storage_used_bytes: int = 0
    storage_used_gb: float = 0.0
    storage_limit_gb: float = 0.0
    storage_percentage: float = 0.0
    remaining_storage_bytes: int = 0
    remaining_storage_gb: float = 0.0
    file_type_breakdown: FileTypeBreakdown = Field(default_factory=FileTypeBreakdown)
    total_files: int = 0
    
    class Config:
        populate_by_name = True
        from_attributes = True