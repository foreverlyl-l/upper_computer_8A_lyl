import secrets
from pathlib import Path
from typing import Any
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
DEFAULT_DATABASE_URL = f"sqlite:///{Path(__file__).resolve().parents[1] / 'access_control.db'}"

class Settings(BaseSettings):
    app_name: str = 'Access Control Backend'
    environment: str = 'development'
    debug: bool = False
    database_url: str = DEFAULT_DATABASE_URL
    secret_key: str = ''
    jwt_algorithm: str = 'HS256'
    access_token_expire_minutes: int = 30
    cors_origins: list[str] = ['http://127.0.0.1:5500', 'http://localhost:5500']
    allowed_hosts: list[str] = ['127.0.0.1', 'localhost']
    enable_docs: bool = False
    auto_seed_default_users: bool = False
    seed_admin_username: str = 'admin'
    seed_admin_password: str = ''
    seed_operator_username: str = 'operator'
    seed_operator_password: str = ''
    admin_totp_secret: str = ''
    admin_totp_issuer: str = '智能门禁系统'
    login_rate_limit_per_minute: int = 8
    login_lockout_seconds: int = 180
    security_headers_enabled: bool = True
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', case_sensitive=False)

    @field_validator('cors_origins', 'allowed_hosts', mode='before')
    @classmethod
    def _parse_csv(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(',') if item.strip()]
        return value

    def finalize_security(self) -> None:
        env = self.environment.lower()
        if not self.secret_key:
            if env == 'production':
                raise RuntimeError('SECRET_KEY must be set in production.')
            self.secret_key = secrets.token_urlsafe(48)
        if len(self.secret_key) < 32:
            raise RuntimeError('SECRET_KEY length must be at least 32 characters.')
        if env == 'production':
            if self.debug:
                raise RuntimeError('DEBUG must be false in production.')
            if self.enable_docs:
                raise RuntimeError('Public docs should be disabled in production.')
            if '*' in self.cors_origins:
                raise RuntimeError('CORS wildcard is forbidden in production.')
            if '*' in self.allowed_hosts:
                raise RuntimeError('allowed_hosts wildcard is forbidden in production.')
            if self.auto_seed_default_users:
                raise RuntimeError('Do not enable auto seeding in production.')
            if not self.admin_totp_secret:
                raise RuntimeError('ADMIN_TOTP_SECRET must be set in production.')
settings = Settings()
settings.finalize_security()
