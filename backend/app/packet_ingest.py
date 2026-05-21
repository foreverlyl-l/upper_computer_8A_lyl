import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session
from .models import AccessRecord, Device, DeviceEventLog
ALARM_REASONS = {'101': 'invalid card', '102': 'password error', '103': 'password locked', '201': 'tamper vibration', '301': 'wifi failure'}

@dataclass(frozen=True)
class DevicePacketIngestResult:
    accepted: bool
    event_id: int
    record_id: int | None
    device_id: str
    event_type: str
    action: str

def _as_text(value: Any, default: str='') -> str:
    if value is None:
        return default
    return str(value).strip()

def _normalize_value(value: str) -> str | None:
    cleaned = value.strip()
    if cleaned.lower() in {'none', 'null'}:
        return None
    return cleaned

def parse_pipe_device_packet(raw_packet: str) -> dict[str, Any]:
    raw_packet = raw_packet.strip()
    if not raw_packet:
        raise ValueError('empty device packet')
    parts = [part.strip() for part in raw_packet.split('|')]
    packet_name = parts[0].strip()
    if not packet_name:
        raise ValueError('missing device packet type')
    payload: dict[str, Any] = {'raw_type': packet_name, '_raw': raw_packet}
    packet_type = packet_name.upper()
    if packet_type in {'DAILY', 'EVENT', 'ALARM'}:
        payload['type'] = packet_type.lower()
    elif packet_type.startswith('DOOR_STATUS'):
        payload['type'] = 'event'
        payload['event'] = 'door_status'
        if ':' in packet_name:
            payload['status'] = packet_name.split(':', 1)[1].strip()
    else:
        payload['type'] = 'event'
        payload['event'] = 'message'
        payload['message'] = raw_packet
    for part in parts[1:]:
        if not part:
            continue
        if '=' not in part:
            payload.setdefault('_unparsed', []).append(part)
            continue
        key, value = part.split('=', 1)
        key = key.strip()
        if not key:
            continue
        payload[key] = _normalize_value(value)
    return payload

def normalize_device_payload(payload: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, str):
        return parse_pipe_device_packet(payload)
    if not isinstance(payload, dict):
        raise ValueError('device payload must be an object or raw packet string')
    normalized = dict(payload)
    if 'type' not in normalized and 'raw_type' in normalized:
        normalized['type'] = _as_text(normalized['raw_type']).lower()
    normalized['type'] = _as_text(normalized.get('type'), 'event').lower()
    return normalized

def _device_id_from(payload: dict[str, Any], source_ip: str='') -> str:
    device_id = _as_text(payload.get('device_id') or payload.get('device'))
    if device_id:
        return device_id
    if source_ip:
        return f'udp-{source_ip}'
    return 'unknown-device'

def _has_explicit_device_id(payload: dict[str, Any]) -> bool:
    return bool(_as_text(payload.get('device_id') or payload.get('device')))

def _person_from(payload: dict[str, Any]) -> str:
    return _as_text(payload.get('person_name') or payload.get('person_id') or payload.get('uid') or payload.get('card_uid'), 'unknown-person')

def _credential_from(payload: dict[str, Any]) -> str:
    uid = _as_text(payload.get('person_id') or payload.get('uid') or payload.get('card_uid'))
    if uid:
        return f'RFID-{uid}'
    event = _as_text(payload.get('event') or payload.get('action'), 'device-event')
    return event

def _ensure_device(db: Session, device_id: str, now: datetime) -> Device:
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if device is None:
        device = Device(device_id=device_id, name=f'ESP32 Door {device_id}', is_online=True, mode='UDP', firmware='unknown', last_heartbeat=now)
        db.add(device)
        db.flush()
    else:
        device.is_online = True
        device.last_heartbeat = now
    return device

def _record_daily_event(db: Session, payload: dict[str, Any], device_id: str, now: datetime) -> AccessRecord:
    action = _as_text(payload.get('action'), 'enter').lower()
    reason_map = {'enter': 'device enter', 'leave': 'device leave'}
    record = AccessRecord(device_id=device_id, person_name=_person_from(payload), person_department='', credential=_credential_from(payload), result='pass', reason=reason_map.get(action, f'device daily {action}'), occurred_at=now)
    db.add(record)
    db.flush()
    return record

def _record_alarm_event(db: Session, payload: dict[str, Any], device_id: str, now: datetime) -> AccessRecord:
    code = _as_text(payload.get('situation_code'), 'unknown')
    record = AccessRecord(device_id=device_id, person_name=_person_from(payload), person_department='', credential=f'ALARM-{code}', result='reject', reason=ALARM_REASONS.get(code, f'alarm {code}'), occurred_at=now)
    db.add(record)
    db.flush()
    return record

def _record_runtime_event(db: Session, payload: dict[str, Any], device_id: str, now: datetime) -> AccessRecord | None:
    event = _as_text(payload.get('event')).lower()
    if event == 'card_access' and _as_text(payload.get('result')).lower() == 'denied':
        record = AccessRecord(device_id=device_id, person_name=_person_from(payload), person_department='', credential=_credential_from(payload), result='reject', reason='card denied', occurred_at=now)
    elif event == 'password_error':
        record = AccessRecord(device_id=device_id, person_name='PIN user', person_department='', credential='PIN', result='reject', reason=f"password error count={_as_text(payload.get('error_count'), '1')}", occurred_at=now)
    elif event == 'locked':
        record = AccessRecord(device_id=device_id, person_name='PIN user', person_department='', credential='PIN', result='reject', reason='password locked', occurred_at=now)
    else:
        return None
    db.add(record)
    db.flush()
    return record

def ingest_device_payload(db: Session, payload: dict[str, Any] | str, *, source_ip: str='', received_at: datetime | None=None) -> DevicePacketIngestResult:
    now = received_at or datetime.utcnow()
    normalized = normalize_device_payload(payload)
    device_id = _device_id_from(normalized, source_ip)
    event_type = _as_text(normalized.get('type'), 'event').lower()
    action = _as_text(normalized.get('action') or normalized.get('event'))
    situation_code = _as_text(normalized.get('situation_code'))
    if _has_explicit_device_id(normalized) or event_type in {'daily', 'alarm'}:
        _ensure_device(db, device_id, now)
    log = DeviceEventLog(device_id=device_id, event_type=event_type, action=action, situation_code=situation_code, raw_payload=json.dumps(normalized, ensure_ascii=False, sort_keys=True), source_ip=source_ip, received_at=now)
    db.add(log)
    db.flush()
    record: AccessRecord | None = None
    if event_type == 'daily':
        record = _record_daily_event(db, normalized, device_id, now)
    elif event_type == 'alarm':
        record = _record_alarm_event(db, normalized, device_id, now)
    elif event_type == 'event':
        record = _record_runtime_event(db, normalized, device_id, now)
    return DevicePacketIngestResult(accepted=True, event_id=log.id, record_id=record.id if record else None, device_id=device_id, event_type=event_type, action=action)
