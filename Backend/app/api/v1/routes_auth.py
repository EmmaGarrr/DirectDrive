from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from app.services.auth_service import create_access_token, verify_password, get_password_hash, get_current_user
from app.models.user import UserCreate, UserInDB, Token, UserProfileResponse
from app.services.storage_service import StorageService
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

@router.get("/users/me", response_model=UserProfileResponse)
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    # Get full user document from database
    user_doc = db.users.find_one({"_id": current_user.id}, {"hashed_password": 0})
    if not user_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Calculate storage data
    storage_data = StorageService.calculate_user_storage(current_user.id)
    
    # Build enhanced profile response
    return StorageService.build_user_profile_response(user_doc, storage_data)