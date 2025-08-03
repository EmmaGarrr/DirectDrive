from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from enum import Enum

class UserRole(str, Enum):
    REGULAR = "regular"
    ADMIN = "admin" 
    SUPERADMIN = "superadmin"

class UserBase(BaseModel):
    email: EmailStr
    role: Optional[UserRole] = UserRole.REGULAR
    is_admin: Optional[bool] = False

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