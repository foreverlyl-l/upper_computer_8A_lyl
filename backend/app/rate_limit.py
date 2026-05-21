from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
_WINDOW = timedelta(minutes=1)
_failed_attempts: dict[str, deque[datetime]] = defaultdict(deque)
_locked_until: dict[str, datetime] = {}

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _prune(key: str, now: datetime) -> None:
    attempts = _failed_attempts[key]
    while attempts and now - attempts[0] > _WINDOW:
        attempts.popleft()

def enforce_login_rate_limit(key: str, limit_per_minute: int, lockout_seconds: int) -> None:
    now = _utcnow()
    locked = _locked_until.get(key)
    if locked and locked > now:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail='Too many login attempts. Please retry later.')
    if locked and locked <= now:
        _locked_until.pop(key, None)
    _prune(key, now)
    if len(_failed_attempts[key]) >= limit_per_minute:
        _locked_until[key] = now + timedelta(seconds=lockout_seconds)
        _failed_attempts[key].clear()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail='Too many login attempts. Please retry later.')

def register_login_failure(key: str, limit_per_minute: int, lockout_seconds: int) -> None:
    now = _utcnow()
    _prune(key, now)
    _failed_attempts[key].append(now)
    if len(_failed_attempts[key]) >= limit_per_minute:
        _locked_until[key] = now + timedelta(seconds=lockout_seconds)
        _failed_attempts[key].clear()

def clear_login_failures(key: str) -> None:
    _failed_attempts.pop(key, None)
    _locked_until.pop(key, None)
