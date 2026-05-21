import json
from datetime import date, datetime, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import AccessRecord, AttendanceAdjustment, Device, DeviceEventLog, ManualOpenCommand, PersonCardBinding, User
from ..schemas import AccessRecordPublic, AttendancePublic, AttendanceStatusUpdateRequest, AttendanceStatusUpdateResponse, DeviceCreateRequest, DeviceDetailResponse, DeviceEventPublic, DevicePublic, ManualOpenResponse, MyActivityResponse, PersonCardBindingCreateRequest, PersonCardBindingPublic, PersonCardBindingUpdateRequest, ROLE_PERMISSIONS, UserCreateRequest, UserListPublic, UserPublic, UserUpdateRequest
from ..security import get_password_hash
router = APIRouter(prefix='/api', tags=['access'])
DEVICE_ONLINE_GRACE_SECONDS = 120
LOCAL_TIME_OFFSET = timedelta(hours=8)
ALARM_REASONS = {'101': 'invalid card', '102': 'password error', '103': 'password locked', '201': 'tamper vibration', '301': 'wifi failure'}
ALLOWED_ATTENDANCE_STATUS = {'正常', '迟到', '在岗', '早退', '缺勤', '请假'}

def _local_now() -> datetime:
    return datetime.utcnow() + LOCAL_TIME_OFFSET

def _user_public(user: User) -> UserPublic:
    return UserPublic(id=user.id, username=user.username, display_name=user.display_name, role=user.role, permissions=ROLE_PERMISSIONS.get(user.role, []))

def _fmt_hms(dt: datetime) -> str:
    return dt.strftime('%H:%M:%S')

def _humanize_heartbeat(dt: datetime) -> str:
    seconds = max(0, int((_local_now() - dt).total_seconds()))
    if seconds < 10:
        return '刚刚'
    if seconds < 60:
        return f'{seconds} 秒前'
    if seconds < 3600:
        return f'{seconds // 60} 分钟前'
    return f'{seconds // 3600} 小时前'

def _device_public(item: Device) -> DevicePublic:
    heartbeat_age = max(0, int((_local_now() - item.last_heartbeat).total_seconds()))
    return DevicePublic(id=item.device_id, name=item.name, online=item.is_online and heartbeat_age <= DEVICE_ONLINE_GRACE_SECONDS, mode=item.mode, firmware=item.firmware, last_heartbeat=_humanize_heartbeat(item.last_heartbeat))

def _normalize_card_uid(value: str) -> str:
    return value.strip().lower()

def _binding_display_name(binding: PersonCardBinding, users_by_id: dict[int, User]) -> str:
    if binding.display_name.strip():
        return binding.display_name.strip()
    user = users_by_id.get(binding.user_id or 0)
    if user and user.display_name.strip():
        return user.display_name.strip()
    return binding.card_uid

def _load_card_bindings(db: Session) -> list[PersonCardBinding]:
    return db.query(PersonCardBinding).filter(PersonCardBinding.is_active == True).all()

def _users_by_id(db: Session, bindings: list[PersonCardBinding]) -> dict[int, User]:
    user_ids = sorted({item.user_id for item in bindings if item.user_id})
    if not user_ids:
        return {}
    return {item.id: item for item in db.query(User).filter(User.id.in_(user_ids)).all()}

def _person_card_lookup(db: Session) -> dict[str, dict[str, str]]:
    bindings = _load_card_bindings(db)
    users_by_id = _users_by_id(db, bindings)
    return {_normalize_card_uid(item.card_uid): {'display_name': _binding_display_name(item, users_by_id), 'department': item.department or '未分组'} for item in bindings}

def _user_card_uids(db: Session, user: User) -> list[str]:
    bindings = db.query(PersonCardBinding).filter(PersonCardBinding.is_active == True, or_(PersonCardBinding.user_id == user.id, PersonCardBinding.display_name == user.display_name)).all()
    return [_normalize_card_uid(item.card_uid) for item in bindings]

def _record_public(item: AccessRecord, person_lookup: dict[str, dict[str, str]] | None=None) -> AccessRecordPublic:
    person = item.person_name
    if person_lookup:
        card_uid = ''
        if item.credential.startswith('RFID-'):
            card_uid = _normalize_card_uid(item.credential.removeprefix('RFID-'))
        elif item.person_name:
            card_uid = _normalize_card_uid(item.person_name)
        if card_uid in person_lookup:
            person = person_lookup[card_uid]['display_name']
    return AccessRecordPublic(time=_fmt_hms(item.occurred_at), device=item.device_id, person=person, credential=item.credential, result=item.result, reason=item.reason)

def _event_text(item: DeviceEventLog) -> str:
    if item.event_type == 'daily':
        if item.action == 'enter':
            return f'{item.device_id} card enter'
        if item.action == 'leave':
            return f'{item.device_id} card leave'
        return f"{item.device_id} daily {item.action or '-'}"
    if item.event_type == 'alarm':
        reason = ALARM_REASONS.get(item.situation_code, item.situation_code or 'unknown')
        return f'{item.device_id} alarm {reason}'
    if item.event_type == 'event':
        return f"{item.device_id} {item.action or 'event'}"
    return f'{item.device_id} {item.event_type}'

def _event_public(item: DeviceEventLog) -> DeviceEventPublic:
    return DeviceEventPublic(time=_fmt_hms(item.received_at), device=item.device_id, type=item.event_type, action=item.action, situation_code=item.situation_code, source_ip=item.source_ip, text=_event_text(item), raw_payload=item.raw_payload)

def _load_event_payload(item: DeviceEventLog) -> dict:
    try:
        payload = json.loads(item.raw_payload)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}

def _payload_has_value(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() not in {'', 'none', 'null', '--'}

def _default_attendance_status(first_dt: datetime, last_dt: datetime) -> str:
    status = '正常'
    if first_dt.time() > datetime.strptime('09:00:00', '%H:%M:%S').time():
        status = '迟到'
    if (_local_now() - last_dt).total_seconds() < 3600 * 2:
        status = '在岗'
    return status

@router.post('/users', response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreateRequest, db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    username = payload.username.strip().lower()
    display_name = payload.display_name.strip()
    exists = db.query(User).filter(User.username == username).first()
    if exists:
        raise HTTPException(status_code=409, detail='Username already exists')
    user = User(username=username, display_name=display_name, password_hash=get_password_hash(payload.password), role=payload.role, is_active=payload.is_active)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_public(user)

def _user_list_public(user: User) -> UserListPublic:
    return UserListPublic(id=user.id, username=user.username, display_name=user.display_name, role=user.role, is_active=user.is_active, permissions=ROLE_PERMISSIONS.get(user.role, []))

def _resolve_binding_user(db: Session, user_id: int | None, username: str | None) -> User | None:
    if user_id is not None:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail='User not found')
        return user
    if username:
        user = db.query(User).filter(User.username == username.strip().lower()).first()
        if not user:
            raise HTTPException(status_code=404, detail='User not found')
        return user
    return None

def _binding_public(binding: PersonCardBinding, user: User | None=None) -> PersonCardBindingPublic:
    return PersonCardBindingPublic(id=binding.id, user_id=binding.user_id, username=user.username if user else '', display_name=binding.display_name, department=binding.department, card_uid=binding.card_uid, is_active=binding.is_active)

@router.get('/users', response_model=list[UserListPublic])
def list_users(db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    items = db.query(User).order_by(User.id.asc()).all()
    return [_user_list_public(item) for item in items]

@router.get('/person-cards', response_model=list[PersonCardBindingPublic])
def list_person_card_bindings(db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    bindings = db.query(PersonCardBinding).order_by(PersonCardBinding.id.asc()).all()
    users_by_id = _users_by_id(db, bindings)
    return [_binding_public(item, users_by_id.get(item.user_id or 0)) for item in bindings]

@router.post('/person-cards', response_model=PersonCardBindingPublic, status_code=status.HTTP_201_CREATED)
def create_person_card_binding(payload: PersonCardBindingCreateRequest, db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    card_uid = _normalize_card_uid(payload.card_uid)
    exists = db.query(PersonCardBinding).filter(PersonCardBinding.card_uid == card_uid).first()
    if exists:
        raise HTTPException(status_code=409, detail='Card UID already exists')
    user = _resolve_binding_user(db, payload.user_id, payload.username)
    binding = PersonCardBinding(user_id=user.id if user else None, card_uid=card_uid, display_name=payload.display_name.strip(), department=(payload.department or '未分组').strip() or '未分组', is_active=payload.is_active)
    db.add(binding)
    db.commit()
    db.refresh(binding)
    return _binding_public(binding, user)

@router.put('/person-cards/{binding_id}', response_model=PersonCardBindingPublic)
def update_person_card_binding(binding_id: int, payload: PersonCardBindingUpdateRequest, db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    binding = db.query(PersonCardBinding).filter(PersonCardBinding.id == binding_id).first()
    if not binding:
        raise HTTPException(status_code=404, detail='Person card binding not found')
    user = None
    if payload.user_id is not None or payload.username is not None:
        user = _resolve_binding_user(db, payload.user_id, payload.username)
        binding.user_id = user.id if user else None
    elif binding.user_id:
        user = db.query(User).filter(User.id == binding.user_id).first()
    if payload.card_uid is not None:
        card_uid = _normalize_card_uid(payload.card_uid)
        exists = db.query(PersonCardBinding).filter(PersonCardBinding.card_uid == card_uid, PersonCardBinding.id != binding_id).first()
        if exists:
            raise HTTPException(status_code=409, detail='Card UID already exists')
        binding.card_uid = card_uid
    if payload.display_name is not None:
        binding.display_name = payload.display_name.strip()
    if payload.department is not None:
        binding.department = payload.department.strip() or '未分组'
    if payload.is_active is not None:
        binding.is_active = payload.is_active
    db.commit()
    db.refresh(binding)
    return _binding_public(binding, user)

@router.delete('/person-cards/{binding_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_person_card_binding(binding_id: int, db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    binding = db.query(PersonCardBinding).filter(PersonCardBinding.id == binding_id).first()
    if not binding:
        raise HTTPException(status_code=404, detail='Person card binding not found')
    db.delete(binding)
    db.commit()
    return None

@router.put('/users/{user_id}', response_model=UserListPublic)
def update_user(user_id: int, payload: UserUpdateRequest, db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail='User not found')
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        user.password_hash = get_password_hash(payload.password)
    db.commit()
    db.refresh(user)
    return _user_list_public(user)

@router.delete('/users/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail='User not found')
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail='Cannot delete yourself')
    db.delete(user)
    db.commit()
    return None

@router.get('/devices', response_model=list[DevicePublic])
def list_devices(db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    items = db.query(Device).order_by(Device.device_id.asc()).all()
    return [_device_public(item) for item in items]

@router.post('/devices', response_model=DevicePublic, status_code=status.HTTP_201_CREATED)
def create_device(payload: DeviceCreateRequest, db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    exists = db.query(Device).filter(Device.device_id == payload.device_id).first()
    if exists:
        raise HTTPException(status_code=409, detail='Device ID already exists')
    now = _local_now()
    item = Device(device_id=payload.device_id, name=payload.name, is_online=payload.online, mode=payload.mode, firmware=payload.firmware, last_heartbeat=now)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _device_public(item)

@router.get('/devices/{device_id}', response_model=DeviceDetailResponse)
def get_device(device_id: str, db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail='Device not found')
    start = _local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    today_pass = db.query(AccessRecord).filter(AccessRecord.device_id == device_id, AccessRecord.result == 'pass', AccessRecord.occurred_at >= start, AccessRecord.occurred_at < end).count()
    return DeviceDetailResponse(device=_device_public(device), today_pass=today_pass)

@router.get('/devices/{device_id}/records', response_model=list[AccessRecordPublic])
def list_device_records(device_id: str, limit: int=Query(default=100, ge=1, le=500), db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    exists = db.query(Device.id).filter(Device.device_id == device_id).first()
    if not exists:
        raise HTTPException(status_code=404, detail='Device not found')
    items = db.query(AccessRecord).filter(AccessRecord.device_id == device_id).order_by(AccessRecord.occurred_at.desc()).limit(limit).all()
    person_lookup = _person_card_lookup(db)
    return [_record_public(item, person_lookup) for item in items]

@router.post('/devices/{device_id}/open', response_model=ManualOpenResponse)
def manual_open_device(device_id: str, db: Session=Depends(get_db), user: User=Depends(get_current_user)):
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail='Device not found')
    now = _local_now()
    cmd = ManualOpenCommand(device_id=device_id, requested_by=user.username, status='accepted', message='open command accepted', requested_at=now)
    db.add(cmd)
    db.commit()
    return ManualOpenResponse(device_id=device_id, accepted=True, message='已下发手动开门指令', requested_at=now.isoformat(timespec='seconds'))

@router.get('/records', response_model=list[AccessRecordPublic])
def list_records(result: Literal['all', 'pass', 'reject']=Query(default='all'), device_id: str | None=Query(default=None), limit: int=Query(default=200, ge=1, le=500), db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    query = db.query(AccessRecord)
    if result != 'all':
        query = query.filter(AccessRecord.result == result)
    if device_id:
        query = query.filter(AccessRecord.device_id == device_id)
    items = query.order_by(AccessRecord.occurred_at.desc()).limit(limit).all()
    person_lookup = _person_card_lookup(db)
    return [_record_public(item, person_lookup) for item in items]

@router.get('/device-events', response_model=list[DeviceEventPublic])
def list_device_events(device_id: str | None=Query(default=None), limit: int=Query(default=50, ge=1, le=500), db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    query = db.query(DeviceEventLog)
    if device_id:
        query = query.filter(DeviceEventLog.device_id == device_id)
    items = query.order_by(DeviceEventLog.received_at.desc()).limit(limit).all()
    return [_event_public(item) for item in items]

@router.get('/attendance', response_model=list[AttendancePublic])
def list_attendance(day: date | None=Query(default=None), db: Session=Depends(get_db), _: User=Depends(get_current_user)):
    target_day = day or _local_now().date()
    start = datetime.combine(target_day, datetime.min.time())
    end = start + timedelta(days=1)
    events = db.query(DeviceEventLog).filter(DeviceEventLog.event_type == 'daily', DeviceEventLog.received_at >= start, DeviceEventLog.received_at < end).order_by(DeviceEventLog.received_at.asc()).all()
    adjustments = db.query(AttendanceAdjustment).filter(AttendanceAdjustment.attendance_date == target_day).all()
    adj_map = {item.person_name: item for item in adjustments}
    person_lookup = _person_card_lookup(db)
    grouped: dict[str, dict] = {}
    for event in events:
        payload = _load_event_payload(event)
        person_id = _normalize_card_uid(str(payload.get('person_id') or payload.get('uid') or payload.get('card_uid') or ''))
        if not person_id:
            continue
        action = str(payload.get('action') or '').strip().lower()
        if action == 'enter':
            if not _payload_has_value(payload.get('enter_time')):
                continue
            item = grouped.setdefault(person_id, {'first_in': event.received_at, 'last_out': event.received_at, 'gates': {}})
            if event.received_at < item['first_in']:
                item['first_in'] = event.received_at
            if event.received_at > item['last_out']:
                item['last_out'] = event.received_at
            item['gates'][event.device_id] = item['gates'].get(event.device_id, 0) + 1
        elif action == 'leave':
            if person_id not in grouped or not _payload_has_value(payload.get('leave_time')):
                continue
            item = grouped[person_id]
            if event.received_at > item['last_out']:
                item['last_out'] = event.received_at
            item['gates'][event.device_id] = item['gates'].get(event.device_id, 0) + 1
    people = set(person_lookup.keys()) | set(grouped.keys())
    results: list[AttendancePublic] = []
    for name in sorted(people):
        item = grouped.get(name)
        person_info = person_lookup.get(name, {})
        display_name = person_info.get('display_name', name)
        if item:
            first_dt = item['first_in']
            last_dt = item['last_out']
            dept = person_info.get('department', '未分组')
            gate_counts = item['gates']
            main_gate = max(gate_counts, key=gate_counts.get)
            default_status = _default_attendance_status(first_dt, last_dt)
            first_in = _fmt_hms(first_dt)
            last_out = _fmt_hms(last_dt)
        else:
            dept = person_info.get('department', '未分组')
            main_gate = '--'
            default_status = '缺勤'
            first_in = '--'
            last_out = '--'
        adjusted = adj_map.get(display_name) or adj_map.get(name)
        status_value = adjusted.status if adjusted else default_status
        results.append(AttendancePublic(name=display_name, dept=dept, first_in=first_in, last_out=last_out, status=status_value, main_gate=main_gate, attendance_date=target_day.isoformat()))
    return results

@router.patch('/attendance/status', response_model=AttendanceStatusUpdateResponse)
def patch_attendance_status(payload: AttendanceStatusUpdateRequest, db: Session=Depends(get_db), user: User=Depends(get_current_user)):
    status_value = payload.status.strip()
    if status_value not in ALLOWED_ATTENDANCE_STATUS:
        raise HTTPException(status_code=422, detail=f"status must be one of: {', '.join(sorted(ALLOWED_ATTENDANCE_STATUS))}")
    target_day = payload.attendance_date or _local_now().date()
    name = payload.person_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail='person_name is required')
    item = db.query(AttendanceAdjustment).filter(AttendanceAdjustment.person_name == name, AttendanceAdjustment.attendance_date == target_day).first()
    if item is None:
        item = AttendanceAdjustment(person_name=name, attendance_date=target_day, status=status_value, updated_by=user.username, note=(payload.note or '').strip())
        db.add(item)
    else:
        item.status = status_value
        item.updated_by = user.username
        item.note = (payload.note or '').strip()
    db.commit()
    db.refresh(item)
    return AttendanceStatusUpdateResponse(person_name=item.person_name, attendance_date=item.attendance_date.isoformat(), status=item.status, note=item.note, updated_by=item.updated_by, updated_at=item.updated_at.isoformat(timespec='seconds'))

@router.get('/me/activity', response_model=MyActivityResponse)
def get_my_activity(day: date | None=Query(default=None), limit: int=Query(default=100, ge=1, le=500), db: Session=Depends(get_db), user: User=Depends(get_current_user)):
    target_day = day or _local_now().date()
    start = datetime.combine(target_day, datetime.min.time())
    end = start + timedelta(days=1)
    person_lookup = _person_card_lookup(db)
    card_uids = _user_card_uids(db, user)
    identity_candidates = []
    if user.display_name and user.display_name.strip():
        identity_candidates.append(user.display_name.strip())
    if user.username and user.username.strip() and (user.username.strip() not in identity_candidates):
        identity_candidates.append(user.username.strip())
    for card_uid in card_uids:
        if card_uid not in identity_candidates:
            identity_candidates.append(card_uid)
    if not identity_candidates:
        return MyActivityResponse(name=user.username, attendance_date=target_day.isoformat(), attendance_status='缺勤', first_in='--', last_out='--', main_gate='--', records=[])
    credential_candidates = [f'RFID-{card_uid}' for card_uid in card_uids]
    if credential_candidates:
        identity_filter = or_(AccessRecord.person_name.in_(identity_candidates), AccessRecord.credential.in_(credential_candidates))
    else:
        identity_filter = AccessRecord.person_name.in_(identity_candidates)
    all_rows = db.query(AccessRecord).filter(identity_filter, AccessRecord.occurred_at >= start, AccessRecord.occurred_at < end).order_by(AccessRecord.occurred_at.asc()).all()
    recent_rows = all_rows[-limit:]
    recent_rows.reverse()
    adjusted = db.query(AttendanceAdjustment).filter(AttendanceAdjustment.person_name.in_(identity_candidates), AttendanceAdjustment.attendance_date == target_day).order_by(AttendanceAdjustment.updated_at.desc()).first()
    if all_rows:
        first_dt = all_rows[0].occurred_at
        last_dt = all_rows[-1].occurred_at
        gate_counts: dict[str, int] = {}
        for item in all_rows:
            gate_counts[item.device_id] = gate_counts.get(item.device_id, 0) + 1
        main_gate = max(gate_counts, key=gate_counts.get)
        default_status = _default_attendance_status(first_dt, last_dt)
        first_in = _fmt_hms(first_dt)
        last_out = _fmt_hms(last_dt)
    else:
        main_gate = '--'
        default_status = '缺勤'
        first_in = '--'
        last_out = '--'
    return MyActivityResponse(name=user.display_name or user.username, attendance_date=target_day.isoformat(), attendance_status=adjusted.status if adjusted else default_status, first_in=first_in, last_out=last_out, main_gate=main_gate, records=[_record_public(item, person_lookup) for item in recent_rows])
