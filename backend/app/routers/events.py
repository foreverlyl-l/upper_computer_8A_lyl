from datetime import datetime, timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..db import get_db
from ..packet_ingest import ingest_device_payload
router = APIRouter(tags=['device-events'])
PC_TIME_OFFSET = timedelta(hours=8)

def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get('x-forwarded-for', '').split(',', 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else '')

async def _read_device_payload(request: Request) -> dict[str, Any] | str:
    content_type = request.headers.get('content-type', '').lower()
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail='Empty device payload')
    if 'application/json' in content_type:
        try:
            parsed = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail='Invalid JSON device payload') from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail='JSON device payload must be an object')
        return parsed
    return body.decode('utf-8', errors='replace')

@router.post('/event')
@router.post('/api/events')
async def receive_device_event(request: Request, db: Session=Depends(get_db)):
    payload = await _read_device_payload(request)
    try:
        result = ingest_device_payload(db, payload, source_ip=_client_ip(request), received_at=datetime.utcnow() + PC_TIME_OFFSET)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {'accepted': result.accepted, 'event_id': result.event_id, 'record_id': result.record_id, 'device_id': result.device_id, 'type': result.event_type, 'action': result.action}
