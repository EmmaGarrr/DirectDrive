# Request filtering middleware to reduce invalid HTTP request warnings
# File: Backend/app/middleware/request_filter.py

from fastapi import Request, Response
from fastapi.responses import PlainTextResponse
import logging

logger = logging.getLogger(__name__)

class RequestFilterMiddleware:
    """
    Middleware to filter out common bot/scanner requests that cause 
    'Invalid HTTP request received' warnings in Uvicorn logs.
    """
    
    def __init__(self, app):
        self.app = app
        
        # Common bot/scanner paths that we want to block early
        self.blocked_paths = {
            '/robots.txt', '/favicon.ico', '/sitemap.xml',
            '/.env', '/.git', '/admin', '/wp-admin', '/wp-login.php',
            '/phpMyAdmin', '/phpmyadmin', '/mysql', '/sql',
            '/config', '/backup', '/test', '/debug',
            '/api/v1/health', '/health', '/status', '/ping'
        }
        
        # Common bot user agents
        self.blocked_user_agents = {
            'bot', 'crawler', 'spider', 'scraper', 'scanner',
            'curl', 'wget', 'python-requests', 'go-http-client'
        }

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            
            # Check for blocked paths
            path = request.url.path.lower()
            if any(blocked in path for blocked in self.blocked_paths):
                response = PlainTextResponse("Not Found", status_code=404)
                await response(scope, receive, send)
                return
            
            # Check for blocked user agents
            user_agent = request.headers.get("user-agent", "").lower()
            if any(blocked in user_agent for blocked in self.blocked_user_agents):
                response = PlainTextResponse("Forbidden", status_code=403)
                await response(scope, receive, send)
                return
                
            # Check for common scanner requests (no proper HTTP headers)
            if not request.headers.get("host") or not request.headers.get("user-agent"):
                response = PlainTextResponse("Bad Request", status_code=400)
                await response(scope, receive, send)
                return
        
        # Continue with normal request processing
        await self.app(scope, receive, send)
