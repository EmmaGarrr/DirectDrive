from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from app.services.auth_service import create_access_token, verify_password, get_password_hash, get_current_user, create_reset_token, verify_reset_token, mark_reset_token_used
from app.services.email_service import email_service
from app.models.user import UserCreate, UserInDB, Token, PasswordChange, UserProfile, ForgotPassword, ResetPassword
from app.db.mongodb import db
from datetime import timedelta

router = APIRouter()

@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = db.users.find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=1440)
    access_token = create_access_token(
        data={"sub": user["email"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/register", response_model=UserInDB)
async def register_user(user: UserCreate):
    db_user = db.users.find_one({"email": user.email})
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    hashed_password = get_password_hash(user.password)
    user_dict = user.model_dump()
    user_dict.pop("password")
    user_dict["hashed_password"] = hashed_password
    
    # In MongoDB, the primary key is _id. We'll use the email as the _id for simplicity.
    user_dict["_id"] = user.email 
    
    db.users.insert_one(user_dict)
    
    return UserInDB(**user_dict)

@router.get("/users/me", response_model=UserProfile)
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    # Convert bytes to GB for frontend display
    storage_used_gb = current_user.storage_used_bytes / (1024 ** 3)
    storage_limit_gb = current_user.storage_limit_bytes / (1024 ** 3)
    
    return UserProfile(
        email=current_user.email,
        storage_used_bytes=current_user.storage_used_bytes,
        storage_limit_bytes=current_user.storage_limit_bytes,
        storage_used_gb=round(storage_used_gb, 2),
        storage_limit_gb=round(storage_limit_gb, 2)
    )

@router.post("/change-password")
async def change_password(
    password_data: PasswordChange,
    current_user: UserInDB = Depends(get_current_user)
):
    # Verify current password
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # Hash new password
    new_hashed_password = get_password_hash(password_data.new_password)
    
    # Update password in database
    db.users.update_one(
        {"_id": current_user.email},
        {"$set": {"hashed_password": new_hashed_password}}
    )
    
    return {"message": "Password changed successfully"}

@router.post("/forgot-password")
async def forgot_password(forgot_data: ForgotPassword):
    # Check if user exists
    user = db.users.find_one({"email": forgot_data.email})
    if user:
        # Generate reset token
        reset_token = create_reset_token(forgot_data.email)
        
        # Send password reset email
        reset_url = "http://localhost:4200/reset-password"  # Frontend reset page
        email_sent = email_service.send_password_reset_email(
            forgot_data.email, 
            reset_token, 
            reset_url
        )
        
        if not email_sent:
            # If email service is not configured, log the token for development
            print(f"Password reset token for {forgot_data.email}: {reset_token}")
            print(f"Reset URL: {reset_url}?token={reset_token}")
    
    # Always return success message (security - don't reveal if email exists)
    return {"message": "If the email exists, a password reset link has been sent"}

@router.post("/reset-password")
async def reset_password(reset_data: ResetPassword):
    # Verify reset token
    email = verify_reset_token(reset_data.reset_token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    # Check if user exists
    user = db.users.find_one({"email": email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found"
        )
    
    # Hash new password
    new_hashed_password = get_password_hash(reset_data.new_password)
    
    # Update password in database
    db.users.update_one(
        {"_id": email},
        {"$set": {"hashed_password": new_hashed_password}}
    )
    
    # Mark reset token as used
    mark_reset_token_used(reset_data.reset_token)
    
    return {"message": "Password reset successfully"}

@router.post("/logout")
async def logout(current_user: UserInDB = Depends(get_current_user)):
    # Since we're using JWT tokens, logout is handled client-side by removing the token
    # This endpoint exists for consistency and potential future server-side token blacklisting
    return {"message": "Logged out successfully"}