# # In file: Backend/app/services/google_drive_service.py

# import asyncio
# import io
# import json
# import os
# import threading
# from typing import AsyncGenerator, Generator

# from google.auth.transport.requests import AuthorizedSession
# from google.oauth2.credentials import Credentials
# from googleapiclient.discovery import build
# from googleapiclient.errors import HttpError
# from googleapiclient.http import MediaIoBaseDownload

# from app.core.config import settings

# SCOPES = ['https://www.googleapis.com/auth/drive']


# # --- NEW: Standardized helper function for building an authenticated service client ---
# def get_gdrive_service_for_user():
#     """
#     Builds a Google Drive service client consistently authenticated as the user
#     using the stored OAuth 2.0 refresh token.
#     """
#     creds = Credentials.from_authorized_user_info(
#         info={
#             "client_id": settings.OAUTH_CLIENT_ID,
#             "client_secret": settings.OAUTH_CLIENT_SECRET,
#             "refresh_token": settings.OAUTH_REFRESH_TOKEN,
#         },
#         scopes=SCOPES
#     )
#     return build('drive', 'v3', credentials=creds)


# # --- NEW: Standardized helper function for making direct HTTP requests ---
# def get_authed_session_for_user():
#     """
#     Builds an authorized session object for making direct HTTP requests
#     (like for resumable uploads) as the user.
#     """
#     creds = Credentials.from_authorized_user_info(
#         info={
#             "client_id": settings.OAUTH_CLIENT_ID,
#             "client_secret": settings.OAUTH_CLIENT_SECRET,
#             "refresh_token": settings.OAUTH_REFRESH_TOKEN,
#         },
#         scopes=SCOPES
#     )
#     return AuthorizedSession(creds)


# # --- REWRITTEN and SIMPLIFIED ---
# def create_resumable_upload_session(filename: str, filesize: int) -> str:
#     """
#     Initiates a resumable upload session with Google Drive and returns the session URL.
#     This is now the recommended, direct method.
    
#     Args:
#         filename (str): The name of the file to be uploaded.
#         filesize (int): The total size of the file in bytes.

#     Returns:
#         str: The unique, one-time-use URL for the resumable upload session.
#     """
#     try:
#         # Step 1: Define the file's metadata (name and parent folder).
#         metadata = {
#             'name': filename,
#             'parents': [settings.GOOGLE_DRIVE_FOLDER_ID]
#         }
        
#         # Step 2: Set up the headers for the initiation request.
#         # We tell Google the type of the final content and, crucially, its total size.
#         headers = {
#             'Content-Type': 'application/json; charset=UTF-8',
#             'X-Upload-Content-Type': 'application/octet-stream', # The type of the file data itself
#             'X-Upload-Content-Length': str(filesize)
#         }

#         # Step 3: Get an authenticated session using our new helper function.
#         authed_session = get_authed_session_for_user()
        
#         print("[GDRIVE_SERVICE] Initiating resumable session...")
        
#         # Step 4: Make the POST request to the resumable upload endpoint.
#         init_response = authed_session.post(
#             'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable',
#             headers=headers,
#             data=json.dumps(metadata) # The body contains the metadata.
#         )
#         init_response.raise_for_status() # This will raise an error for non-2xx responses.
        
#         # Step 5: Extract the unique upload URL from the response headers.
#         upload_url = init_response.headers['Location']
#         print(f"[GDRIVE_SERVICE] Session initiated successfully. URL: {upload_url}")
#         return upload_url

#     except HttpError as e:
#         print(f"!!! A Google API HTTP Error occurred: {e.content}")
#         raise e
#     except Exception as e:
#         print(f"!!! An unexpected error occurred in create_resumable_upload_session: {e}")
#         raise e

# # # --- NEW FUNCTION TO BE ADDED ---
# # def stream_gdrive_chunks(gdrive_id: str, chunk_size: int) -> Generator[bytes, None, None]:
# #     """
# #     Yields a file from Google Drive in chunks of a specified size without loading
# #     the whole file into memory. This is for the backend-to-backend transfer.
    
# #     Args:
# #         gdrive_id (str): The ID of the file on Google Drive.
# #         chunk_size (int): The size of each chunk in bytes.

# #     Yields:
# #         bytes: A chunk of the file data.
# #     """
# #     try:
# #         print(f"[GDRIVE_STREAMER] Starting chunked stream for GDrive ID: {gdrive_id}")
# #         service = get_gdrive_service_for_user()
# #         request = service.files().get_media(fileId=gdrive_id)
        
# #         # Use a BytesIO buffer as a temporary holder for the stream downloader
# #         fh = io.BytesIO()
# #         downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_size)
        
# #         done = False
# #         while not done:
# #             status, done = downloader.next_chunk()
# #             if status:
# #                 print(f"[GDRIVE_STREAMER] Downloaded chunk progress: {int(status.progress() * 100)}%")
            
# #             # Yield the downloaded chunk and clear the buffer for the next one
# #             fh.seek(0)
# #             yield fh.read()
# #             fh.seek(0)
# #             fh.truncate(0)
            
# #         print(f"[GDRIVE_STREAMER] Finished chunked stream for {gdrive_id}.")

# #     except Exception as e:
# #         print(f"!!! [GDRIVE_STREAMER] An error occurred during chunked stream: {e}")
# #         raise e
    

# async def stream_gdrive_file(file_id: str) -> AsyncGenerator[bytes, None]:
#     """
#     Asynchronously streams a file from Google Drive using a dedicated thread
#     and an OS pipe to bridge the sync/async gap safely.
#     """
#     read_fd, write_fd = os.pipe()

#     def download_in_thread():
#         writer = None
#         try:
#             print("[DOWNLOAD_THREAD] Starting download...")
#             service = get_gdrive_service_for_user() # Uses the new helper
#             request = service.files().get_media(fileId=file_id)
#             writer = io.FileIO(write_fd, 'wb')
#             downloader = MediaIoBaseDownload(writer, request)
            
#             done = False
#             while not done:
#                 status, done = downloader.next_chunk()
#                 if status:
#                     print(f"[DOWNLOAD_THREAD] Downloaded {int(status.progress() * 100)}%.")

#             print("[DOWNLOAD_THREAD] Download finished.")
#         except Exception as e:
#             print(f"!!! [DOWNLOAD_THREAD] Error: {e}")
#         finally:
#             if writer:
#                 writer.close()

#     download_thread = threading.Thread(target=download_in_thread, daemon=True)
#     download_thread.start()

#     loop = asyncio.get_event_loop()
#     reader = io.FileIO(read_fd, 'rb')
    
#     while True:
#         chunk = await loop.run_in_executor(None, reader.read, 4 * 1024 * 1024)
#         if not chunk:
#             break
#         yield chunk
            
#     print(f"[GDRIVE_SERVICE] Finished streaming file {file_id}")
#     download_thread.join()
#     reader.close()
    

# def delete_file_with_refresh_token(file_id: str):
#     """
#     Deletes a file from Google Drive using a user's OAuth 2.0 refresh token.
#     """
#     try:
#         print(f"[GDRIVE_DELETER] Attempting to delete file {file_id} using user credentials.")
#         service = get_gdrive_service_for_user() # Uses the new helper
#         service.files().delete(fileId=file_id).execute()
#         print(f"[GDRIVE_DELETER] Successfully deleted file {file_id}.")
#     except HttpError as e:
#         print(f"!!! [GDRIVE_DELETER] Google API HTTP Error during deletion: {e.content}")
#     except Exception as e:
#         print(f"!!! [GDRIVE_DELETER] An unexpected error occurred during deletion: {e}")
        
    
# def download_file_from_gdrive(gdrive_id: str) -> io.BytesIO:
#     """
#     Downloads a file from Google Drive into an in-memory BytesIO object.
#     """
#     try:
#         print(f"[GDRIVE_DOWNLOADER] Downloading file {gdrive_id} using user credentials.")
#         service = get_gdrive_service_for_user() # Uses the new helper
#         request = service.files().get_media(fileId=gdrive_id)
#         fh = io.BytesIO()
#         downloader = MediaIoBaseDownload(fh, request)
        
#         done = False
#         while not done:
#             status, done = downloader.next_chunk()
#             print(f"[GDRIVE_DOWNLOADER] Download progress: {int(status.progress() * 100)}%.")
        
#         fh.seek(0)
#         print(f"[GDRIVE_DOWNLOADER] File {gdrive_id} downloaded successfully.")
#         return fh
#     except HttpError as e:
#         print(f"!!! [GDRIVE_DOWNLOADER] Google API HTTP Error during download: {e.content}")
#         raise e
#     except Exception as e:
#         print(f"!!! [GDRIVE_DOWNLOADER] An unexpected error occurred during download: {e}")
#         raise e
    

# # In file: Backend/app/services/google_drive_service.py

# import asyncio
# import io
# import json
# import os
# import threading
# from typing import AsyncGenerator, Generator

# from google.auth.transport.requests import AuthorizedSession
# from google.oauth2.credentials import Credentials
# from googleapiclient.discovery import build
# from googleapiclient.errors import HttpError
# from googleapiclient.http import MediaIoBaseDownload

# from app.core.config import settings

# SCOPES = ['https://www.googleapis.com/auth/drive']

# def get_gdrive_service_for_user():
#     creds = Credentials.from_authorized_user_info(
#         info={
#             "client_id": settings.OAUTH_CLIENT_ID,
#             "client_secret": settings.OAUTH_CLIENT_SECRET,
#             "refresh_token": settings.OAUTH_REFRESH_TOKEN,
#         },
#         scopes=SCOPES
#     )
#     return build('drive', 'v3', credentials=creds)

# def get_authed_session_for_user():
#     creds = Credentials.from_authorized_user_info(
#         info={
#             "client_id": settings.OAUTH_CLIENT_ID,
#             "client_secret": settings.OAUTH_CLIENT_SECRET,
#             "refresh_token": settings.OAUTH_REFRESH_TOKEN,
#         },
#         scopes=SCOPES
#     )
#     return AuthorizedSession(creds)

# def create_resumable_upload_session(filename: str, filesize: int) -> str:
#     try:
#         metadata = {
#             'name': filename,
#             'parents': [settings.GOOGLE_DRIVE_FOLDER_ID]
#         }
#         headers = {
#             'Content-Type': 'application/json; charset=UTF-8',
#             'X-Upload-Content-Type': 'application/octet-stream',
#             'X-Upload-Content-Length': str(filesize)
#         }
#         authed_session = get_authed_session_for_user()
#         print("[GDRIVE_SERVICE] Initiating resumable session...")
#         init_response = authed_session.post(
#             'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable',
#             headers=headers,
#             data=json.dumps(metadata)
#         )
#         init_response.raise_for_status()
#         upload_url = init_response.headers['Location']
#         print(f"[GDRIVE_SERVICE] Session initiated successfully. URL: {upload_url}")
#         return upload_url
#     except HttpError as e:
#         print(f"!!! A Google API HTTP Error occurred: {e.content}")
#         raise e
#     except Exception as e:
#         print(f"!!! An unexpected error occurred in create_resumable_upload_session: {e}")
#         raise e


# # --- THIS IS THE NEW STREAMING FUNCTION FOR THE BACKGROUND WORKER ---
# def stream_gdrive_chunks(gdrive_id: str, chunk_size: int) -> Generator[bytes, None, None]:
#     """
#     Yields a file from Google Drive in fixed-size chunks without loading the
#     whole file into memory. This is for the synchronous Celery worker.
    
#     Args:
#         gdrive_id (str): The ID of the file on Google Drive.
#         chunk_size (int): The size of each chunk in bytes.

#     Yields:
#         bytes: A chunk of the file data, with a size up to chunk_size.
#     """
#     try:
#         print(f"[GDRIVE_STREAMER] Starting chunked stream for GDrive ID: {gdrive_id}")
#         service = get_gdrive_service_for_user()
#         request = service.files().get_media(fileId=gdrive_id)
        
#         # This BytesIO buffer is a small, temporary holder for the downloader.
#         # Its size will never exceed chunk_size.
#         fh = io.BytesIO()
#         downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_size)
        
#         done = False
#         while not done:
#             status, done = downloader.next_chunk()
#             if status:
#                 print(f"[GDRIVE_STREAMER] Streaming progress: {int(status.progress() * 100)}%")
            
#             # After a chunk is downloaded into fh, yield its content and then clear fh.
#             fh.seek(0)
#             yield fh.read()
            
#             # Reset the buffer for the next chunk download.
#             fh.seek(0)
#             fh.truncate(0)
            
#         print(f"[GDRIVE_STREAMER] Finished chunked stream for {gdrive_id}.")

#     except HttpError as e:
#         print(f"!!! [GDRIVE_STREAMER] A Google API error occurred: {e.content}")
#         raise e
#     except Exception as e:
#         print(f"!!! [GDRIVE_STREAMER] An error occurred during chunked stream: {e}")
#         raise e


# # --- THIS FUNCTION IS FOR THE LIVE USER-FACING DOWNLOAD (NO CHANGE) ---
# async def stream_gdrive_file(file_id: str) -> AsyncGenerator[bytes, None]:
#     read_fd, write_fd = os.pipe()

#     def download_in_thread():
#         writer = None
#         try:
#             print("[DOWNLOAD_THREAD] Starting download...")
#             service = get_gdrive_service_for_user()
#             request = service.files().get_media(fileId=file_id)
#             writer = io.FileIO(write_fd, 'wb')
#             downloader = MediaIoBaseDownload(writer, request)
            
#             done = False
#             while not done:
#                 status, done = downloader.next_chunk()
#                 if status:
#                     print(f"[DOWNLOAD_THREAD] Downloaded {int(status.progress() * 100)}%.")
#             print("[DOWNLOAD_THREAD] Download finished.")
#         except Exception as e:
#             print(f"!!! [DOWNLOAD_THREAD] Error: {e}")
#         finally:
#             if writer:
#                 writer.close()

#     download_thread = threading.Thread(target=download_in_thread, daemon=True)
#     download_thread.start()

#     loop = asyncio.get_event_loop()
#     reader = io.FileIO(read_fd, 'rb')
    
#     while True:
#         chunk = await loop.run_in_executor(None, reader.read, 4 * 1024 * 1024)
#         if not chunk:
#             break
#         yield chunk
            
#     print(f"[GDRIVE_SERVICE] Finished streaming file {file_id}")
#     download_thread.join()
#     reader.close()
    

# def delete_file_with_refresh_token(file_id: str):
#     try:
#         print(f"[GDRIVE_DELETER] Attempting to delete file {file_id} using user credentials.")
#         service = get_gdrive_service_for_user()
#         service.files().delete(fileId=file_id).execute()
#         print(f"[GDRIVE_DELETER] Successfully deleted file {file_id}.")
#     except HttpError as e:
#         print(f"!!! [GDRIVE_DELETER] Google API HTTP Error during deletion: {e.content}")
#     except Exception as e:
#         print(f"!!! [GDRIVE_DELETER] An unexpected error occurred during deletion: {e}")
        
    
# --- REMOVED: This function is obsolete and dangerous for large files. ---
# def download_file_from_gdrive(gdrive_id: str) -> io.BytesIO:
#     ...



###########################################################################################################

# In file: Backend/app/services/google_drive_service.py

import asyncio
import io
import json
from typing import AsyncGenerator, Generator

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from app.core.config import settings

SCOPES = ['https://www.googleapis.com/auth/drive']

def get_gdrive_service_for_user():
    creds = Credentials.from_authorized_user_info(
        info={
            "client_id": settings.OAUTH_CLIENT_ID,
            "client_secret": settings.OAUTH_CLIENT_SECRET,
            "refresh_token": settings.OAUTH_REFRESH_TOKEN,
        },
        scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

def get_authed_session_for_user():
    creds = Credentials.from_authorized_user_info(
        info={
            "client_id": settings.OAUTH_CLIENT_ID,
            "client_secret": settings.OAUTH_CLIENT_SECRET,
            "refresh_token": settings.OAUTH_REFRESH_TOKEN,
        },
        scopes=SCOPES
    )
    return AuthorizedSession(creds)

def create_resumable_upload_session(filename: str, filesize: int) -> str:
    try:
        metadata = {
            'name': filename,
            'parents': [settings.GOOGLE_DRIVE_FOLDER_ID]
        }
        headers = {
            'Content-Type': 'application/json; charset=UTF-8',
            'X-Upload-Content-Type': 'application/octet-stream',
            'X-Upload-Content-Length': str(filesize)
        }
        authed_session = get_authed_session_for_user()
        print("[GDRIVE_SERVICE] Initiating resumable session...")
        init_response = authed_session.post(
            'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable',
            headers=headers,
            data=json.dumps(metadata)
        )
        init_response.raise_for_status()
        upload_url = init_response.headers['Location']
        print(f"[GDRIVE_SERVICE] Session initiated successfully. URL: {upload_url}")
        return upload_url
    except HttpError as e:
        print(f"!!! A Google API HTTP Error occurred: {e.content}")
        raise e
    except Exception as e:
        print(f"!!! An unexpected error occurred in create_resumable_upload_session: {e}")
        raise e

# --- This is the synchronous streamer for the Celery worker (no change needed) ---
def stream_gdrive_chunks(gdrive_id: str, chunk_size: int) -> Generator[bytes, None, None]:
    """
    Yields a file from Google Drive in fixed-size chunks. For synchronous workers.
    """
    try:
        service = get_gdrive_service_for_user()
        request = service.files().get_media(fileId=gdrive_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_size)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"[GDRIVE_STREAMER] Celery streaming progress: {int(status.progress() * 100)}%")
            fh.seek(0)
            yield fh.read()
            fh.seek(0)
            fh.truncate(0)
    except HttpError as e:
        print(f"!!! [GDRIVE_STREAMER] A Google API error occurred: {e.content}")
        raise e
    except Exception as e:
        print(f"!!! [GDRIVE_STREAMER] An error occurred during chunked stream: {e}")
        raise e

###################################################################################
# --- NEW ROBUST ASYNC STREAMING FUNCTION FOR LIVE USER-FACING DOWNLOADS ---
###################################################################################
async def async_stream_gdrive_file(gdrive_id: str) -> AsyncGenerator[bytes, None]:
    """
    Asynchronously streams a file from Google Drive.

    This is the modern, robust replacement for the old thread-based approach.
    It uses asyncio.to_thread to run the blocking GDrive library calls in a
    non-blocking way, making it safe and efficient for FastAPI.
    """
    try:
        service = get_gdrive_service_for_user()
        request = service.files().get_media(fileId=gdrive_id)
        
        # Use an in-memory binary stream as a buffer for chunks.
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        
        done = False
        while not done:
            # Run the blocking downloader.next_chunk() in a separate thread
            # managed by asyncio, and await its completion.
            status, done = await asyncio.to_thread(downloader.next_chunk)

            if status:
                print(f"[ASYNC_GDRIVE_DOWNLOAD] Downloaded {int(status.progress() * 100)}%.")

            # Yield the content of the buffer and then clear it
            fh.seek(0)
            yield fh.read()
            fh.seek(0)
            fh.truncate(0)
            
        print(f"[ASYNC_GDRIVE_DOWNLOAD] Finished streaming file {gdrive_id}")

    except HttpError as e:
        # This will catch API errors, e.g., if the file was deleted from Drive.
        print(f"!!! [ASYNC_GDRIVE_DOWNLOAD] Google API error: {e.content}")
        raise e
    except Exception as e:
        print(f"!!! [ASYNC_GDRIVE_DOWNLOAD] Unexpected error during stream: {e}")
        raise e


def delete_file_with_refresh_token(file_id: str):
    try:
        service = get_gdrive_service_for_user()
        service.files().delete(fileId=file_id).execute()
        print(f"[GDRIVE_DELETER] Successfully deleted file {file_id}.")
    except HttpError as e:
        print(f"!!! [GDRIVE_DELETER] Google API HTTP Error during deletion: {e.content}")
    except Exception as e:
        print(f"!!! [GDRIVE_DELETER] An unexpected error occurred during deletion: {e}")