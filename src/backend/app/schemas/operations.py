import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import AlertSeverity, RoleCode, SchedulerMode

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _email(v: str) -> str:
    v = v.strip().lower()
    if not _EMAIL.match(v) or len(v) > 255:
        raise ValueError("Enter a valid email address")
    return v


class LoginIn(Strict):
    email: str
    password: str = Field(min_length=1, max_length=200)

    _e = field_validator("email")(_email)


class UserIn(Strict):
    email: str
    full_name: str = Field(min_length=2, max_length=120)
    role: RoleCode
    password: str = Field(min_length=10, max_length=200)

    _e = field_validator("email")(_email)


class UserPatch(Strict):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    role: RoleCode | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=200)


class OverrideIn(Strict):
    action: Literal["reschedule", "charge_now", "cancel"]
    charger_id: int | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    target_soc: float | None = Field(default=None, gt=0, le=100)
    reason: str = Field(min_length=5, max_length=500)
    preempt: bool = False
    hold_hours: float | None = Field(default=None, gt=0, le=72)

    @model_validator(mode="after")
    def _check(self):
        for v in (self.start_at, self.end_at):
            if v is not None and v.tzinfo is None:
                raise ValueError("Datetimes must include a timezone offset")
        if self.action == "reschedule" and (self.start_at is None or self.charger_id is None):
            raise ValueError("Rescheduling needs a charger and a start time")
        return self


class ManualReservationIn(Strict):
    vehicle_id: int
    charger_id: int
    start_at: datetime | None = None
    end_at: datetime | None = None
    target_soc: float | None = Field(default=None, gt=0, le=100)
    reason: str = Field(min_length=5, max_length=500)
    emergency: bool = False
    preempt: bool = False

    @model_validator(mode="after")
    def _check(self):
        for v in (self.start_at, self.end_at):
            if v is not None and v.tzinfo is None:
                raise ValueError("Datetimes must include a timezone offset")
        return self


class RunDecisionIn(Strict):
    reason: str = Field(default="", max_length=500)


class SessionStartIn(Strict):
    vehicle_id: int
    charger_id: int
    target_soc: float | None = Field(default=None, gt=0, le=100)


class SessionStopIn(Strict):
    reason: str = Field(default="Stopped by operator", min_length=3, max_length=160)


class AlertIn(Strict):
    severity: AlertSeverity = AlertSeverity.WARNING
    title: str = Field(min_length=4, max_length=200)
    message: str = Field(min_length=4, max_length=4000)
    vehicle_id: int | None = None
    charger_id: int | None = None
    station_id: int | None = None


class AlertActionIn(Strict):
    note: str = Field(default="", max_length=2000)


class ResolveIn(Strict):
    note: str = Field(min_length=3, max_length=2000)


class AdvanceIn(Strict):
    minutes: int = Field(ge=1, le=180)


class ResetIn(Strict):
    simulation_enabled: bool = False
    scheduler_mode: SchedulerMode = SchedulerMode.BASELINE
    history_days: int = Field(default=30, ge=0, le=60)


class ModeIn(Strict):
    mode: SchedulerMode


class SyncVehicle(Strict):
    external_ref: str = Field(min_length=1, max_length=64)
    registration: str = Field(min_length=2, max_length=32)
    battery_profile: str
    home_station_code: str
    current_soc: float | None = Field(default=None, ge=0, le=100)
    required_departure_soc: float | None = Field(default=None, gt=0, le=100)
    priority_category: str | None = None


class SyncTrip(Strict):
    external_ref: str = Field(min_length=1, max_length=64)
    vehicle_external_ref: str | None = None
    vehicle_registration: str | None = None
    origin_station_code: str
    destination: str = Field(min_length=2, max_length=160)
    distance_km: float = Field(ge=0, le=2000)
    energy_kwh: float | None = Field(default=None, ge=0)
    required_soc: float | None = Field(default=None, gt=0, le=100)
    departure_at: datetime
    return_at: datetime | None = None
    priority: str = "normal"
    cancelled: bool = False


class FleetSyncIn(Strict):
    vehicles: list[SyncVehicle] = Field(default_factory=list, max_length=5000)
    trips: list[SyncTrip] = Field(default_factory=list, max_length=20000)
