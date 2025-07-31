# server/backend/app/services/auth_service.py (Updated)

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.core.config import settings
from app.db.mongodb import db
from app.models.user import TokenData, UserInDB
import secrets
import string

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# This one requires a token and raises an error if it's missing
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

# --- NEW: This one makes the token optional ---
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def generate_reset_token() -> str:
    """Generate a secure random token for password reset"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(32))

def create_reset_token(email: str) -> str:
    """Create a password reset token and store it in the database"""
    reset_token = generate_reset_token()
    expires_at = datetime.utcnow() + timedelta(hours=1)  # 1 hour expiration
    
    # Store reset token in database
    db.password_reset_tokens.insert_one({
        "email": email,
        "reset_token": reset_token,
        "expires_at": expires_at,
        "used": False
    })
    
    return reset_token

def verify_reset_token(reset_token: str) -> Optional[str]:
    """Verify a reset token and return the associated email if valid"""
    token_doc = db.password_reset_tokens.find_one({
        "reset_token": reset_token,
        "used": False,
        "expires_at": {"$gt": datetime.utcnow()}
    })
    
    if token_doc:
        return token_doc["email"]
    return None

def mark_reset_token_used(reset_token: str):
    """Mark a reset token as used"""
    db.password_reset_tokens.update_one(
        {"reset_token": reset_token},
        {"$set": {"used": True}}
    )

# This function remains for protected routes like /users/me
async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        raise credentials_exception
    
    user = db.users.find_one({"email": token_data.email})
    if user is None:
        raise credentials_exception
    
    return UserInDB(**user)

# --- NEW: Function for optional authentication ---
# async def get_current_user_optional(token: Optional[str] = Depends(oauth2_scheme_optional)) -> Optional[UserInDB]:
#     if token is None:
#         return None # No token provided, return None for anonymous user
#     try:
#         payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
#         email: str = payload.get("sub")
#         if email is None:
#             return None # Invalid token payload
#     except JWTError:
#         return None # Token is invalid or expired

#     user_doc = db.users.find_one({"email": email})
#     if user_doc is None:
#         return None # User not found in DB
    
#     return UserInDB(**user_doc)

async def get_current_user_optional(token: Optional[str] = Depends(oauth2_scheme_optional)) -> Optional[UserInDB]:
    """
    A dependency that tries to get a user from a token.
    If the token is invalid, missing, or the user doesn't exist,
    it returns None instead of raising an error.
    """
    if token is None:
        # This is the case for a completely anonymous user (no Authorization header)
        return None
        
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            # Token is valid but doesn't contain the user identifier
            return None
        
        user = db.users.find_one({"email": email})
        if user is None:
            # Token is for a user that no longer exists
            return None
            
        return UserInDB(**user)
    except JWTError:
        # Token is malformed, expired, or has an invalid signature.
        # For an optional endpoint, we treat this as an anonymous user.
        return None

# Add this function to the end of auth_service.py

async def try_get_current_user(token: str = Depends(oauth2_scheme)) -> Optional[UserInDB]:
    """
    A dependency that tries to get a user from a token.
    If the token is invalid, missing, or the user doesn't exist,
    it returns None instead of raising an error.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            return None
        
        user_data = db.users.find_one({"email": email})
        if user_data is None:
            return None
            
        return UserInDB(**user_data)
    except (JWTError, AttributeError):
        # This will catch errors from an invalid token or if no token is provided
        return None