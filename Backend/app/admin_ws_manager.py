# File: Backend/app/admin_ws_manager.py

from fastapi import WebSocket
from typing import List

class AdminConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print("Admin client connected.")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print("Admin client disconnected.")

    async def broadcast(self, message: str):
        # Send a message to all connected admin clients
        for connection in self.active_connections:
            await connection.send_text(message)

# Create a single, global instance of the manager that our app can use
admin_manager = AdminConnectionManager()
