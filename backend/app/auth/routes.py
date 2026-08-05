"""
[PENANGGUNG JAWAB: Anggota B]
Endpoint: POST /api/auth/register, POST /api/auth/login,
          GET /api/auth/me, POST /api/auth/change-password
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import (
    UserRegister,
    UserLogin,
    TokenResponse,
    UserResponse,
    ChangePasswordRequest,
)
from app.auth.utils import hash_password, verify_password, create_access_token, get_current_user
from app.auth.rate_limit import check_rate_limit, record_failed_attempt, clear_attempts

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    check_rate_limit(payload.email)

    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        record_failed_attempt(payload.email)
        raise HTTPException(status_code=401, detail="Email atau password salah")

    clear_attempts(payload.email)
    token = create_access_token(user_id=user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Password lama tidak sesuai")

    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password berhasil diubah"}