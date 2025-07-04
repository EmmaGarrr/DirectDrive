# import httpx
# from app.core.config import settings

# # Construct the base URL for the Telegram Bot API
# TELEGRAM_API_URL = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"

# async def upload_chunk_to_telegram(chunk: bytes, filename: str) -> int:
#     """
#     Uploads a single binary chunk as a document to the designated Telegram channel.

#     Args:
#         chunk: The binary data of the file chunk.
#         filename: The name to give the uploaded document chunk.

#     Returns:
#         The message_id of the uploaded document in the channel.
        
#     Raises:
#         Exception: If the Telegram API returns an error.
#     """
#     # Use an async context manager for the HTTP client
#     async with httpx.AsyncClient(timeout=60.0) as client:
#         print(f"[TELEGRAM_SERVICE] Uploading chunk '{filename}' to channel {settings.TELEGRAM_CHANNEL_ID}...")
        
#         # Define the API endpoint for sending documents
#         url = f"{TELEGRAM_API_URL}/sendDocument"
        
#         # Define the parameters for the request
#         params = {'chat_id': settings.TELEGRAM_CHANNEL_ID}
        
#         # Prepare the file data for a multipart/form-data request.
#         # The key 'document' is required by the Telegram API.
#         files = {'document': (filename, chunk, 'application/octet-stream')}
        
#         try:
#             # Send the POST request
#             response = await client.post(url, params=params, files=files)
            
#             # Check for HTTP errors (e.g., 400, 401, 500)
#             response.raise_for_status()
            
#             # Parse the JSON response from Telegram
#             data = response.json()
            
#             # Check for API-level errors (e.g., chat not found)
#             if data.get("ok"):
#                 message_id = data['result']['message_id']
#                 print(f"[TELEGRAM_SERVICE] Chunk uploaded successfully. Message ID: {message_id}")
#                 return message_id
#             else:
#                 error_description = data.get("description", "Unknown Telegram API error")
#                 raise Exception(f"Telegram API Error: {error_description}")

#         except httpx.RequestError as e:
#             print(f"!!! An HTTP error occurred while contacting Telegram: {e}")
#             raise Exception(f"Failed to connect to Telegram: {e}") from e
        
        
# async def get_file_path_from_telegram(message_id: int) -> str:
#     """Gets the internal file_path for a document from its message_id."""
#     async with httpx.AsyncClient(timeout=30.0) as client:
#         url = f"{TELEGRAM_API_URL}/getFile"
#         params = {'message_id': message_id, 'chat_id': settings.TELEGRAM_CHANNEL_ID}
        
#         # This is a bit of a trick. The getFile method officially wants a 'file_id',
#         # but we can often get it to work with a message_id in the target chat.
#         # A more robust way involves forwarding, but this is simpler. Let's try it first.
#         # The official way is to get the file_id from the message object when it's sent.
#         # Our upload function returns a message_id, but the full message object has the file_id.
#         # This is a known complexity in the Bot API.
#         # Let's assume a simplified getFile for now.
        
#         # A more robust get_file_path would be:
#         # 1. Bot receives message
#         # 2. Store `message.document.file_id`
#         # 3. Use that `file_id` in the `getFile` call.
#         # Since we only have message_id, we'll try this simpler approach.
#         # In a real production app, storing the file_id is better.
        
#         # For now, let's just make a placeholder that would need to be fleshed out
#         # if the direct getFile by message_id doesn't work.
#         # The getFile method requires file_id. We cannot get file_id from message_id.
#         # So we must change the upload logic slightly. Let's do that now.
#         # THIS IS A REQUIRED CHANGE - THE API DOES NOT SUPPORT THIS.
#         # WE WILL MODIFY THE UPLOAD FUNCTION TO RETURN MORE DATA.
#         pass # We will replace this entire service file below.


# import httpx
# from typing import AsyncGenerator, List, Dict
# from app.core.config import settings

# TELEGRAM_API_URL = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"

# # THIS IS NOW CORRECT
# async def upload_chunk_to_telegram(chunk: bytes, filename: str) -> Dict[str, any]:
#     """
#     Uploads a chunk and returns the full message object, which contains the crucial file_id.
#     """
#     async with httpx.AsyncClient(timeout=60.0) as client:
#         url = f"{TELEGRAM_API_URL}/sendDocument"
#         params = {'chat_id': settings.TELEGRAM_CHANNEL_ID}
#         files = {'document': (filename, chunk, 'application/octet-stream')}
        
#         response = await client.post(url, params=params, files=files)
#         response.raise_for_status()
#         data = response.json()
        
#         if data.get("ok"):
#             # Return the entire 'document' part of the result
#             return data['result']['document']
#         else:
#             raise Exception(f"Telegram API Error: {data.get('description')}")

# async def get_file_path(file_id: str) -> str:
#     """Gets the internal file_path from a file_id."""
#     async with httpx.AsyncClient(timeout=30.0) as client:
#         url = f"{TELEGRAM_API_URL}/getFile"
#         params = {'file_id': file_id}
#         response = await client.get(url, params=params)
#         response.raise_for_status()
#         data = response.json()
#         if data.get("ok"):
#             return data['result']['file_path']
#         else:
#             raise Exception(f"Telegram getFile Error: {data.get('description')}")

# async def stream_file_from_telegram(file_ids: List[str]) -> AsyncGenerator[bytes, None]:
#     """
#     Accepts a list of Telegram file_ids, fetches each one, and streams its content.
#     """
#     print(f"[TELEGRAM_SERVICE] Streaming {len(file_ids)} chunks from Telegram.")
#     for file_id in file_ids:
#         try:
#             file_path = await get_file_path(file_id)
#             download_url = f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}"
            
#             async with httpx.AsyncClient(timeout=60.0) as client:
#                 async with client.stream("GET", download_url) as response:
#                     response.raise_for_status()
#                     async for chunk in response.aiter_bytes():
#                         yield chunk
#             print(f"[TELEGRAM_SERVICE] Finished streaming chunk with file_id: {file_id}")
#         except Exception as e:
#             print(f"!!! [TELEGRAM_SERVICE] Failed to stream chunk {file_id}: {e}")
#             # In a real app, you might want to handle this more gracefully
#             # For now, it will just stop the download.
#             break



import httpx
from app.core.config import settings

# Define the base API URL for the Telegram bot
TELEGRAM_API_URL = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
# Define a safe chunk size, slightly less than the 20MB technical limit.
TELEGRAM_CHUNK_SIZE_BYTES = 15 * 1024 * 1024

async def upload_file_chunk(chunk_data: bytes, filename: str) -> int:
    """
    Uploads a single binary chunk as a document to the designated Telegram channel.
    
    Args:
        chunk_data: The binary content of the file chunk.
        filename: The name to give the document in Telegram.

    Returns:
        The message_id of the uploaded document in the channel.
    """
    async with httpx.AsyncClient(timeout=900.0) as client:
        url = f"{TELEGRAM_API_URL}/sendDocument"
        
        params = {'chat_id': settings.TELEGRAM_CHANNEL_ID}
        
        # Prepare the file for multipart upload
        files = {'document': (filename, chunk_data, 'application/octet-stream')}
        
        try:
            print(f"[TELEGRAM_SERVICE] Uploading chunk '{filename}' to channel {settings.TELEGRAM_CHANNEL_ID}...")
            response = await client.post(url, params=params, files=files)
            response.raise_for_status()  # Raise an exception for HTTP 4xx/5xx errors
            
            data = response.json()
            if data.get('ok'):
                message_id = data['result']['message_id']
                print(f"[TELEGRAM_SERVICE] Chunk uploaded successfully. Message ID: {message_id}")
                return message_id
            else:
                raise Exception(f"Telegram API Error: {data.get('description', 'Unknown error')}")

        except httpx.RequestError as e:
            print(f"!!! [TELEGRAM_SERVICE] HTTP request failed: {e}")
            raise