from typing import Optional
from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    # MongoDB
    MONGODB_URI: str
    DATABASE_NAME: str

    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHANNEL_ID: str

    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    
    # NEW: OAuth 2.0 Credentials
    OAUTH_CLIENT_ID: str
    OAUTH_CLIENT_SECRET: str
    OAUTH_REFRESH_TOKEN: str
    GOOGLE_DRIVE_FOLDER_ID: Optional[str] = None
    
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    ADMIN_WEBSOCKET_TOKEN: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Set this to make sure the credential path is relative to the project root
        # os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')


settings = Settings()
