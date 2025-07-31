from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str

class UserInDB(UserBase):
    id: str = Field(..., alias="_id")
    hashed_password: str
    storage_used_bytes: int = Field(default=0)  # Track used storage
    storage_limit_bytes: int = Field(default=10737418240)  # 10GB limit for authenticated users

    class Config:
        populate_by_name = True
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

class ForgotPassword(BaseModel):
    email: EmailStr

class ResetPassword(BaseModel):
    reset_token: str
    new_password: str

class UserProfile(BaseModel):
    email: EmailStr
    storage_used_bytes: int
    storage_limit_bytes: int
    storage_used_gb: float = Field(default=0.0)
    storage_limit_gb: float = Field(default=10.0)
    
    class Config:
        from_attributes = True