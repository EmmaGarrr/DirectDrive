# In file: Backend/app/core/config.py

from typing import Optional, List
from pydantic_settings import BaseSettings
from pydantic import BaseModel
import os

# A model to hold the configuration for a single Google Drive account
class GoogleAccountConfig(BaseModel):
    id: str
    client_id: str
    client_secret: str
    refresh_token: str
    folder_id: Optional[str] = None

class Settings(BaseSettings):
    # MongoDB
    MONGODB_URI: str
    DATABASE_NAME: str

    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    
    # Google Drive account credentials
    GDRIVE_ACCOUNT_1_CLIENT_ID: Optional[str] = None
    GDRIVE_ACCOUNT_1_CLIENT_SECRET: Optional[str] = None
    GDRIVE_ACCOUNT_1_REFRESH_TOKEN: Optional[str] = None
    GDRIVE_ACCOUNT_1_FOLDER_ID: Optional[str] = None

    GDRIVE_ACCOUNT_2_CLIENT_ID: Optional[str] = None
    GDRIVE_ACCOUNT_2_CLIENT_SECRET: Optional[str] = None
    GDRIVE_ACCOUNT_2_REFRESH_TOKEN: Optional[str] = None
    GDRIVE_ACCOUNT_2_FOLDER_ID: Optional[str] = None

    GDRIVE_ACCOUNT_3_CLIENT_ID: Optional[str] = None
    GDRIVE_ACCOUNT_3_CLIENT_SECRET: Optional[str] = None
    GDRIVE_ACCOUNT_3_REFRESH_TOKEN: Optional[str] = None
    GDRIVE_ACCOUNT_3_FOLDER_ID: Optional[str] = None
    
    GDRIVE_ACCOUNTS: List[GoogleAccountConfig] = []

    # --- NEW: Hetzner Storage Box Credentials ---
    HETZNER_WEBDAV_URL: Optional[str] = None
    HETZNER_USERNAME: Optional[str] = None
    HETZNER_PASSWORD: Optional[str] = None

    ADMIN_WEBSOCKET_TOKEN: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = 'ignore'

# Initialize settings from .env
settings = Settings()

# Manually parse and populate the GDRIVE_ACCOUNTS list
for i in range(1, 11):
    client_id = getattr(settings, f'GDRIVE_ACCOUNT_{i}_CLIENT_ID', None)
    client_secret = getattr(settings, f'GDRIVE_ACCOUNT_{i}_CLIENT_SECRET', None)
    refresh_token = getattr(settings, f'GDRIVE_ACCOUNT_{i}_REFRESH_TOKEN', None)
    folder_id = getattr(settings, f'GDRIVE_ACCOUNT_{i}_FOLDER_ID', None)

    if all([client_id, client_secret, refresh_token, folder_id]):
        settings.GDRIVE_ACCOUNTS.append(
            GoogleAccountConfig(
                id=f'account_{i}',
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                folder_id=folder_id
            )
        )

if not settings.GDRIVE_ACCOUNTS:
    print("WARNING: No Google Drive accounts configured in .env file. Primary uploads will fail.")