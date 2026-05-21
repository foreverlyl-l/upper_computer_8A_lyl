from sqlalchemy.orm import Session
from .models import User
from .security import get_password_hash

def ensure_default_users(db: Session, enabled: bool, admin_username: str, admin_password: str, operator_username: str, operator_password: str) -> None:
    if not enabled:
        return
    if len(admin_password) < 12 or len(operator_password) < 12:
        raise RuntimeError('Seed passwords must be at least 12 characters.')
    seed_users = [{'username': admin_username, 'display_name': '系统管理员', 'password': admin_password, 'role': 'admin'}, {'username': operator_username, 'display_name': '值班员', 'password': operator_password, 'role': 'operator'}]
    for item in seed_users:
        existing = db.query(User).filter(User.username == item['username']).first()
        if existing:
            continue
        user = User(username=item['username'], display_name=item['display_name'], password_hash=get_password_hash(item['password']), role=item['role'], is_active=True)
        db.add(user)
    db.commit()
