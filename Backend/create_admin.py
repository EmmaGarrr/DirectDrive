#!/usr/bin/env python3
"""
Simple script to create an admin user for DirectDrive
Run this on the VPS after deploying the admin authentication system
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the app directory to the Python path
sys.path.append(str(Path(__file__).parent))

from app.db.mongodb import db
from app.services.admin_auth_service import create_admin_user
from app.models.admin import AdminUserCreate, UserRole

async def create_admin():
    """Create a superadmin user"""
    
    # Default admin credentials (you can change these)
    email = "admin@directdrive.com"
    password = "admin123"
    
    admin_data = AdminUserCreate(
        email=email,
        password=password,
        role=UserRole.SUPERADMIN
    )
    
    try:
        print(f"Creating superadmin user: {email}")
        result = await create_admin_user(admin_data)
        
        print("✅ Admin user created successfully!")
        print(f"Email: {result.data.email}")
        print(f"Role: {result.data.role}")
        print(f"Password: {password}")
        print("\nYou can now login with these credentials!")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        if "already exists" in str(e).lower():
            print("Admin user already exists!")

if __name__ == "__main__":
    asyncio.run(create_admin()) 