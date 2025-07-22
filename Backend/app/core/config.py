# # from typing import Optional
# # from pydantic_settings import BaseSettings
# # import os

# # class Settings(BaseSettings):
# #     # MongoDB
# #     MONGODB_URI: str
# #     DATABASE_NAME: str

# #     # Telegram
# #     TELEGRAM_BOT_TOKEN: str
# #     TELEGRAM_CHANNEL_ID: str

# #     # JWT
# #     JWT_SECRET_KEY: str
# #     JWT_ALGORITHM: str
# #     ACCESS_TOKEN_EXPIRE_MINUTES: int
    
# #     # NEW: OAuth 2.0 Credentials
# #     OAUTH_CLIENT_ID: str
# #     OAUTH_CLIENT_SECRET: str
# #     OAUTH_REFRESH_TOKEN: str
# #     GOOGLE_DRIVE_FOLDER_ID: Optional[str] = None
    
# #     CELERY_BROKER_URL: str = "redis://localhost:6379/0"
# #     ADMIN_WEBSOCKET_TOKEN: str

# #     class Config:
# #         env_file = ".env"
# #         env_file_encoding = "utf-8"
# #         # Set this to make sure the credential path is relative to the project root
# #         # os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')


# # settings = Settings()


# # In file: Backend/app/core/config.py

# from typing import Optional, List
# from pydantic_settings import BaseSettings
# from pydantic import BaseModel
# import os

# # NEW: A model to hold the configuration for a single Google Drive account
# class GoogleAccountConfig(BaseModel):
#     id: str
#     client_id: str
#     client_secret: str
#     refresh_token: str
#     folder_id: Optional[str] = None

# class Settings(BaseSettings):
#     # MongoDB
#     MONGODB_URI: str
#     DATABASE_NAME: str

#     # JWT
#     JWT_SECRET_KEY: str
#     JWT_ALGORITHM: str
#     ACCESS_TOKEN_EXPIRE_MINUTES: int
    
#     # MODIFIED: Load multiple Google Drive account credentials from the .env file
#     # We will manually parse them into the GoogleAccountConfig model below.
#     GDRIVE_ACCOUNT_1_CLIENT_ID: Optional[str] = None
#     GDRIVE_ACCOUNT_1_CLIENT_SECRET: Optional[str] = None
#     GDRIVE_ACCOUNT_1_REFRESH_TOKEN: Optional[str] = None
#     GDRIVE_ACCOUNT_1_FOLDER_ID: Optional[str] = None

#     GDRIVE_ACCOUNT_2_CLIENT_ID: Optional[str] = None
#     GDRIVE_ACCOUNT_2_CLIENT_SECRET: Optional[str] = None
#     GDRIVE_ACCOUNT_2_REFRESH_TOKEN: Optional[str] = None
#     GDRIVE_ACCOUNT_2_FOLDER_ID: Optional[str] = None

#     GDRIVE_ACCOUNT_3_CLIENT_ID: Optional[str] = None
#     GDRIVE_ACCOUNT_3_CLIENT_SECRET: Optional[str] = None
#     GDRIVE_ACCOUNT_3_REFRESH_TOKEN: Optional[str] = None
#     GDRIVE_ACCOUNT_3_FOLDER_ID: Optional[str] = None
    
#     # This will be populated after initialization
#     GDRIVE_ACCOUNTS: List[GoogleAccountConfig] = []

#     ADMIN_WEBSOCKET_TOKEN: Optional[str] = None

#     class Config:
#         env_file = ".env"
#         env_file_encoding = "utf-8"
#         # --- THIS IS THE FIX ---
#         # Tell Pydantic to ignore any extra variables it finds in the .env file
#         extra = 'ignore'

# # Initialize settings from .env
# settings = Settings()

# # NEW: Manually parse and populate the GDRIVE_ACCOUNTS list
# # This loop will check for accounts up to a reasonable number (e.g., 10)
# for i in range(1, 11):
#     client_id = getattr(settings, f'GDRIVE_ACCOUNT_{i}_CLIENT_ID', None)
#     client_secret = getattr(settings, f'GDRIVE_ACCOUNT_{i}_CLIENT_SECRET', None)
#     refresh_token = getattr(settings, f'GDRIVE_ACCOUNT_{i}_REFRESH_TOKEN', None)
#     folder_id = getattr(settings, f'GDRIVE_ACCOUNT_{i}_FOLDER_ID', None)

#     if all([client_id, client_secret, refresh_token, folder_id]):
#         settings.GDRIVE_ACCOUNTS.append(
#             GoogleAccountConfig(
#                 id=f'account_{i}',
#                 client_id=client_id,
#                 client_secret=client_secret,
#                 refresh_token=refresh_token,
#                 folder_id=folder_id
#             )
#         )

# if not settings.GDRIVE_ACCOUNTS:
#     print("WARNING: No Google Drive accounts configured in .env file. Uploads will fail.")






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