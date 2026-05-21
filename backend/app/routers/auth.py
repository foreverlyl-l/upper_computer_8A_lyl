from datetime import timedelta
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..rate_limit import clear_login_failures, enforce_login_rate_limit, register_login_failure
from ..schemas import LoginRequest, ROLE_PERMISSIONS, TokenResponse, UserPublic
from ..security import create_access_token, verify_password
router = APIRouter(prefix='/api/auth', tags=['auth'])

def to_user_public(user: User) -> UserPublic:
    return UserPublic(id=user.id, username=user.username, display_name=user.display_name, role=user.role, permissions=ROLE_PERMISSIONS.get(user.role, []))

def _client_identity(request: Request, username: str) -> str:
    cf_ip = (request.headers.get('cf-connecting-ip') or '').strip()
    xff = (request.headers.get('x-forwarded-for') or '').split(',')[0].strip()
    ip = cf_ip or xff or (request.client.host if request.client else 'unknown')
    return f'{ip}:{username.lower()}'

def _verify_admin_totp(totp_code: str | None) -> bool:
    if not settings.admin_totp_secret:
        return False
    code = (totp_code or '').strip().replace(' ', '')
    if len(code) != 6 or not code.isdigit():
        return False
    totp = pyotp.TOTP(settings.admin_totp_secret)
    return bool(totp.verify(code, valid_window=1))

@router.post('/login', response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session=Depends(get_db)):
    key = _client_identity(request, payload.username)
    enforce_login_rate_limit(key=key, limit_per_minute=settings.login_rate_limit_per_minute, lockout_seconds=settings.login_lockout_seconds)
    invalid_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid username, password, or dynamic code')
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not user.is_active or (not verify_password(payload.password, user.password_hash)):
        register_login_failure(key=key, limit_per_minute=settings.login_rate_limit_per_minute, lockout_seconds=settings.login_lockout_seconds)
        raise invalid_error
    if user.role == 'admin' and (not _verify_admin_totp(payload.totp_code)):
        register_login_failure(key=key, limit_per_minute=settings.login_rate_limit_per_minute, lockout_seconds=settings.login_lockout_seconds)
        raise invalid_error
    clear_login_failures(key)
    expire_delta = timedelta(minutes=settings.access_token_expire_minutes)
    token = create_access_token(subject=user.username, role=user.role, expires_delta=expire_delta)
    return TokenResponse(access_token=token, expires_in=int(expire_delta.total_seconds()), user=to_user_public(user))

@router.get('/me', response_model=UserPublic)
def me(current_user: User=Depends(get_current_user)):
    return to_user_public(current_user)
