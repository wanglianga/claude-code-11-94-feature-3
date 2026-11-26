"""Pydantic 请求/响应模型"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------- auth ----------
class LoginIn(BaseModel):
    username: str


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    team: str | None = None


# ---------- receiving ----------
class TransportEventIn(BaseModel):
    event_type: str = Field(description="collision|water|thermal")
    description: str = ""
    source_doc: str = ""
    case_closed: bool = False


class ReceiveIn(BaseModel):
    batch_no: str
    serial_no: str
    oem: str
    source_vehicle: str
    scan_payload: str = "sim-scanner"
    quarantine_slot: str | None = None
    responsible_team: str | None = None
    events: list[TransportEventIn] = []
    notes: str = ""


class FreezeBatchIn(BaseModel):
    batch_no: str
    reason: str


class QuarantinePackIn(BaseModel):
    serial_no: str
    reason: str


class ReleaseQuarantineIn(BaseModel):
    serial_no: str
    note: str = ""


class UnfreezeBatchIn(BaseModel):
    batch_no: str
    note: str = ""


# ---------- dismantling ----------
class WorkOrderIn(BaseModel):
    serial_no: str
    note: str = ""


class LinkModuleIn(BaseModel):
    work_order_id: int
    module_serial: str
    witness1: str
    witness2: str


class UnknownModuleIn(BaseModel):
    work_order_id: int
    module_serial: str
    reason: str


class ResolveUnknownIn(BaseModel):
    module_serial: str
    parent_serial: str


class RelabelIn(BaseModel):
    entity_type: str = Field(description="pack|module")
    old_serial: str
    new_serial: str
    operator2: str | None = None
    confirm: bool = False


# ---------- inspection ----------
class DeviceIn(BaseModel):
    device_no: str
    name: str
    calibrated_until: datetime


class InspectionIn(BaseModel):
    serial_no: str
    device_no: str
    insulation_pass: bool
    bms_reading_ok: bool
    is_reinspection: bool = False
    note: str = ""


class ThermalCloseIn(BaseModel):
    event_id: int
    closed: bool = True


# ---------- safety ----------
class ApprovalIn(BaseModel):
    serial_no: str
    decision: str = Field(description="echelon|recycle|reinspect")
    purpose: str | None = None
    consignee: str | None = None
    quantity_limit: int | None = None
    rationale: str = ""


# ---------- warehouse ----------
class PickIn(BaseModel):
    picking_id: int


class ShipIn(BaseModel):
    outbound_id: int


class SignOffIn(BaseModel):
    outbound_id: int
    action: str = Field(description="signed|rejected")
    signer: str
    note: str = ""


class RecallIn(BaseModel):
    outbound_id: int
    kind: str = Field(description="recall|return")
    reason: str


class WeighIn(BaseModel):
    serial_no: str
    weight_kg: float


class CloseBatchIn(BaseModel):
    batch_no: str
    explanation: str | None = None
