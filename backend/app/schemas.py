from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
ROLE_PERMISSIONS = {'admin': ['dashboard', 'devices', 'deviceDetail', 'records', 'attendance', 'settings'], 'operator': ['dashboard', 'records', 'attendance'], 'personal': ['myActivity']}

class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str | None = None

class UserPublic(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    permissions: list[str]
    model_config = ConfigDict(from_attributes=True)

class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern='^[A-Za-z0-9_.-]+$')
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    role: Literal['admin', 'operator', 'personal']
    is_active: bool = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_in: int
    user: UserPublic

class HealthResponse(BaseModel):
    status: str

class DevicePublic(BaseModel):
    id: str
    name: str
    online: bool
    mode: str
    firmware: str
    last_heartbeat: str

class DeviceCreateRequest(BaseModel):
    device_id: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=1, max_length=100)
    mode: str = Field(min_length=1, max_length=20)
    online: bool = True
    firmware: str = Field(default='v1.0.0', min_length=1, max_length=40)

class DeviceDetailResponse(BaseModel):
    device: DevicePublic
    today_pass: int

class AccessRecordPublic(BaseModel):
    time: str
    device: str
    person: str
    credential: str
    result: str
    reason: str

class DeviceEventPublic(BaseModel):
    time: str
    device: str
    type: str
    action: str
    situation_code: str
    source_ip: str
    text: str
    raw_payload: str

class AttendancePublic(BaseModel):
    name: str
    dept: str
    first_in: str
    last_out: str
    status: str
    main_gate: str
    attendance_date: str

class MyActivityResponse(BaseModel):
    name: str
    attendance_date: str
    attendance_status: str
    first_in: str
    last_out: str
    main_gate: str
    records: list[AccessRecordPublic]

class AttendanceStatusUpdateRequest(BaseModel):
    person_name: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=20)
    attendance_date: date | None = None
    note: str = Field(default='', max_length=200)

class AttendanceStatusUpdateResponse(BaseModel):
    person_name: str
    attendance_date: str
    status: str
    note: str
    updated_by: str
    updated_at: str

class ManualOpenResponse(BaseModel):
    device_id: str
    accepted: bool
    message: str
    requested_at: str

class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Literal['admin', 'operator', 'personal'] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)

class UserListPublic(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    permissions: list[str]
    model_config = ConfigDict(from_attributes=True)

class PersonCardBindingPublic(BaseModel):
    id: int
    user_id: int | None
    username: str
    display_name: str
    department: str
    card_uid: str
    is_active: bool

class PersonCardBindingCreateRequest(BaseModel):
    user_id: int | None = None
    username: str | None = Field(default=None, min_length=1, max_length=50)
    display_name: str = Field(min_length=1, max_length=100)
    department: str = Field(default='未分组', max_length=100)
    card_uid: str = Field(min_length=1, max_length=80)
    is_active: bool = True

class PersonCardBindingUpdateRequest(BaseModel):
    user_id: int | None = None
    username: str | None = Field(default=None, min_length=1, max_length=50)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    card_uid: str | None = Field(default=None, min_length=1, max_length=80)
    is_active: bool | None = None
