# Enhanced request filtering middleware to reduce invalid HTTP request warnings
# and handle WebSocket connection filtering
# File: Backend/app/middleware/request_filter.py

from fastapi import Request, Response
from fastapi.responses import PlainTextResponse
import logging
import sys

logger = logging.getLogger(__name__)

class RequestFilterMiddleware:
    """
    Enhanced middleware to filter out common bot/scanner requests that cause 
    'Invalid HTTP request received' warnings in Uvicorn logs.
    Handles both HTTP requests and WebSocket connection attempts.
    """
    
    def __init__(self, app):
        self.app = app
        
        # Common bot/scanner paths that we want to block early
        self.blocked_paths = {
            '/robots.txt', '/favicon.ico', '/sitemap.xml',
            '/.env', '/.git', '/admin', '/wp-admin', '/wp-login.php',
            '/phpMyAdmin', '/phpmyadmin', '/mysql', '/sql',
            '/config', '/backup', '/test', '/debug',
            '/api/v1/health', '/health', '/status', '/ping',
            # Add common WebSocket probe paths
            '/ws', '/websocket', '/socket.io', '/sockjs'
        }
        
        # Common bot user agents
        self.blocked_user_agents = {
            'bot', 'crawler', 'spider', 'scraper', 'scanner',
            'curl', 'wget', 'python-requests', 'go-http-client',
            'masscan', 'nmap', 'zmap', 'nikto'
        }
        
        # Valid WebSocket endpoints in our application
        self.valid_websocket_paths = {
            '/ws_api/upload/', '/ws_admin'
        }

    def _is_bot_request(self, headers):
        """Check if request appears to be from a bot/scanner"""
        user_agent = headers.get("user-agent", "").lower()
        return any(blocked in user_agent for blocked in self.blocked_user_agents)
    
    def _is_malformed_websocket(self, scope):
        """Check if WebSocket connection attempt is malformed/invalid"""
        headers = dict(scope.get("headers", []))
        
        # Convert byte headers to strings
        str_headers = {}
        for key, value in headers.items():
            if isinstance(key, bytes):
                key = key.decode('latin1')
            if isinstance(value, bytes):
                value = value.decode('latin1')
            str_headers[key.lower()] = value.lower()
        
        # Check for proper WebSocket upgrade headers
        connection = str_headers.get('connection', '')
        upgrade = str_headers.get('upgrade', '')
        ws_key = str_headers.get('sec-websocket-key', '')
        
        # If it's supposed to be a WebSocket but missing required headers
        if 'upgrade' in connection or 'websocket' in upgrade:
            if not ws_key or 'websocket' not in upgrade:
                return True
        
        return False
    
    def _is_valid_websocket_path(self, path):
        """Check if WebSocket path is valid for our application"""
        return any(path.startswith(valid_path) for valid_path in self.valid_websocket_paths)

    async def _send_websocket_close(self, send, code=1008, reason="Invalid request"):
        """Send WebSocket close frame for invalid connections"""
        try:
            await send({
                "type": "websocket.close",
                "code": code,
                "reason": reason
            })
        except Exception:
            # If we can't send close frame, connection is already broken
            pass

    async def __call__(self, scope, receive, send):
        # Handle HTTP requests
        if scope["type"] == "http":
            request = Request(scope, receive)
            
            # Check for blocked paths
            path = request.url.path.lower()
            if any(blocked in path for blocked in self.blocked_paths):
                response = PlainTextResponse("Not Found", status_code=404)
                await response(scope, receive, send)
                return
            
            # Check for blocked user agents
            if self._is_bot_request(request.headers):
                response = PlainTextResponse("Forbidden", status_code=403)
                await response(scope, receive, send)
                return
                
            # Check for common scanner requests (no proper HTTP headers)
            if not request.headers.get("host") or not request.headers.get("user-agent"):
                response = PlainTextResponse("Bad Request", status_code=400)
                await response(scope, receive, send)
                return
        
        # Handle WebSocket connections
        elif scope["type"] == "websocket":
            path = scope.get("path", "")
            
            # Block bot WebSocket attempts immediately
            headers = dict(scope.get("headers", []))
            if self._is_bot_request({k.decode('latin1') if isinstance(k, bytes) else k: 
                                   v.decode('latin1') if isinstance(v, bytes) else v 
                                   for k, v in headers.items()}):
                await self._send_websocket_close(send, 1008, "Bot requests not allowed")
                print(f"[WEBSOCKET_FILTER] Blocked bot WebSocket attempt to {path}")
                return
            
            # Check if WebSocket path is valid for our application
            if not self._is_valid_websocket_path(path):
                await self._send_websocket_close(send, 1008, "Invalid WebSocket endpoint")
                print(f"[WEBSOCKET_FILTER] Blocked invalid WebSocket path: {path}")
                return
            
            # Check for malformed WebSocket requests
            if self._is_malformed_websocket(scope):
                await self._send_websocket_close(send, 1002, "Malformed WebSocket request")
                print(f"[WEBSOCKET_FILTER] Blocked malformed WebSocket request to {path}")
                return
        
        # Continue with normal request processing
        try:
            await self.app(scope, receive, send)
        except Exception as e:
            # Catch and suppress common WebSocket parsing errors that cause log spam
            error_msg = str(e).lower()
            if any(err in error_msg for err in ['invalid http request', 'websocket', 'upgrade']):
                # Suppress these specific errors that are caused by bot probes
                print(f"[WEBSOCKET_FILTER] Suppressed invalid request error: {type(e).__name__}")
                return
            # Re-raise other exceptions
            raise
