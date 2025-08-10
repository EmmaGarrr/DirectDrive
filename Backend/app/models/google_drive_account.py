from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from bson import ObjectId

class GoogleDriveAccountDB(BaseModel):
    """Database model for Google Drive accounts"""
    id: Optional[ObjectId] = Field(default=None, alias="_id")
    account_id: str = Field(..., description="Unique account identifier")
    email: str = Field(..., description="Service account email")
    alias: str = Field(..., description="Human-readable account alias")
    # OAuth 2.0 fields (for user accounts)
    client_id: Optional[str] = Field(None, description="OAuth client ID")
    client_secret: Optional[str] = Field(None, description="OAuth client secret")
    refresh_token: Optional[str] = Field(None, description="OAuth refresh token")
    # Service account fields
    private_key: Optional[str] = Field(None, description="Service account private key")
    private_key_id: Optional[str] = Field(None, description="Service account private key ID")
    project_id: Optional[str] = Field(None, description="Google Cloud project ID")
    # Common fields
    folder_id: Optional[str] = Field(None, description="Google Drive folder ID")
    folder_name: Optional[str] = Field(None, description="Google Drive folder name")
    folder_path: Optional[str] = Field(None, description="Google Drive folder path")
    is_active: bool = Field(default=True, description="Whether account is active for uploads")
    storage_used: int = Field(default=0, description="Storage used in bytes")
    storage_quota: int = Field(default=0, description="Storage quota in bytes")
    files_count: int = Field(default=0, description="Number of files in account")
    last_activity: Optional[datetime] = Field(default=None, description="Last activity timestamp")
    health_status: str = Field(default="unknown", description="Account health status")
    performance_score: float = Field(default=0.0, description="Performance score (0-100)")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Account creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")
    last_quota_check: Optional[datetime] = Field(default=None, description="Last time quota was checked")
    last_health_check: Optional[datetime] = Field(default=None, description="Last time health was checked")

    model_config = {
        "validate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_schema_extra": {
            "examples": [
                {
                    "account_id": "account_123",
                    "email": "service@example.com",
                    "alias": "Primary Storage",
                    "is_active": True
                }
            ]
        }
    }
    
    def to_config(self):
        """Convert to GoogleAccountConfig for use with Google Drive service"""
        from app.core.config import GoogleAccountConfig
        
        # Ensure we have OAuth credentials
        if not all([self.client_id, self.client_secret, self.refresh_token]):
            raise ValueError(f"Account {self.account_id} missing OAuth credentials for Google Drive API")
        
        return GoogleAccountConfig(
            id=self.account_id,
            client_id=self.client_id,
            client_secret=self.client_secret,
            refresh_token=self.refresh_token,
            folder_id=self.folder_id
        )

class GoogleDriveAccountCreate(BaseModel):
    """Model for creating new Google Drive accounts"""
    email: str = Field(..., description="Service account email")
    alias: str = Field(..., description="Human-readable account alias")
    # OAuth 2.0 fields (for user accounts)
    client_id: Optional[str] = Field(None, description="OAuth client ID")
    client_secret: Optional[str] = Field(None, description="OAuth client secret")
    refresh_token: Optional[str] = Field(None, description="OAuth refresh token")
    # Service account fields
    service_account_key: Optional[str] = Field(None, description="Service account JSON key")
    private_key: Optional[str] = Field(None, description="Service account private key")
    private_key_id: Optional[str] = Field(None, description="Service account private key ID")
    project_id: Optional[str] = Field(None, description="Google Cloud project ID")
    folder_id: Optional[str] = Field(None, description="Google Drive folder ID")

class GoogleDriveAccountUpdate(BaseModel):
    """Model for updating Google Drive accounts"""
    alias: Optional[str] = Field(None, description="Human-readable account alias")
    is_active: Optional[bool] = Field(None, description="Whether account is active for uploads")
    folder_id: Optional[str] = Field(None, description="Google Drive folder ID")

class GoogleDriveAccountResponse(BaseModel):
    """Response model for Google Drive accounts"""
    account_id: str
    email: str
    alias: str
    is_active: bool
    storage_used: int
    storage_quota: int
    files_count: int
    last_activity: Optional[datetime]
    health_status: str
    performance_score: float
    storage_used_formatted: str
    storage_quota_formatted: str
    storage_percentage: float
    created_at: datetime
    updated_at: datetime
    # New folder information fields
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
    folder_path: Optional[str] = None 