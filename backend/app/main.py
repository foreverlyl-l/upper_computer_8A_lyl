from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import settings
from .db import Base, SessionLocal, engine
from .models import User
from .routers.access import router as access_router
from .routers.auth import router as auth_router
from .routers.events import router as events_router
from .schemas import HealthResponse
from .security import decode_token
from .seed import ensure_default_users
app = FastAPI(title=settings.app_name, debug=settings.debug, docs_url='/docs' if settings.enable_docs else None, redoc_url='/redoc' if settings.enable_docs else None, openapi_url='/openapi.json' if settings.enable_docs else None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'], allow_headers=['Authorization', 'Content-Type'])
PUBLIC_API_PATHS = {'/api/health', '/api/auth/login', '/api/auth/me', '/api/events'}
ROLE_ALLOWED_PREFIXES: dict[str, list[tuple[str, str]]] = {'admin': [('*', '/api')], 'operator': [('GET', '/api/devices'), ('GET', '/api/device-events'), ('GET', '/api/records'), ('GET', '/api/attendance')], 'personal': [('GET', '/api/me/activity')]}

def _path_matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f'{prefix}/')

def _is_role_allowed(role: str, method: str, path: str) -> bool:
    rules = ROLE_ALLOWED_PREFIXES.get(role, [])
    for allow_method, allow_prefix in rules:
        if (allow_method == '*' or allow_method == method) and _path_matches_prefix(path, allow_prefix):
            return True
    return False

@app.middleware('http')
async def harden_and_guard_api(request: Request, call_next):
    path = request.url.path.rstrip('/') or '/'
    if request.method != 'OPTIONS' and path.startswith('/api/') and (path not in PUBLIC_API_PATHS):
        auth_header = request.headers.get('authorization', '')
        if not auth_header.lower().startswith('bearer '):
            return JSONResponse(status_code=401, content={'detail': 'Missing bearer token'})
        token = auth_header.split(' ', 1)[1].strip()
        try:
            payload = decode_token(token)
            username = payload.get('sub')
            token_role = payload.get('role')
            if not username:
                raise ValueError('invalid token')
        except ValueError:
            return JSONResponse(status_code=401, content={'detail': 'Invalid token'})
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user or not user.is_active:
                return JSONResponse(status_code=401, content={'detail': 'Invalid token'})
            if token_role and token_role != user.role:
                return JSONResponse(status_code=401, content={'detail': 'Invalid token'})
            if not _is_role_allowed(user.role, request.method, path):
                return JSONResponse(status_code=403, content={'detail': 'Insufficient permissions'})
        finally:
            db.close()
    response = await call_next(request)
    if settings.security_headers_enabled:
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store'
    return response

@app.on_event('startup')
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_default_users(db=db, enabled=settings.auto_seed_default_users, admin_username=settings.seed_admin_username, admin_password=settings.seed_admin_password, operator_username=settings.seed_operator_username, operator_password=settings.seed_operator_password)
    finally:
        db.close()

@app.get('/api/health', response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status='ok')
app.include_router(auth_router)
app.include_router(access_router)
app.include_router(events_router)
