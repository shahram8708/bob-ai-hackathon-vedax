from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import SystemConfig
from app.models.base import utcnow
from app.models.enums import SchedulerMode

CONFIG_KEY = "operational"


class OperationalConfig(BaseModel):
    timezone: str = Field(default_factory=lambda: get_settings().fleet_timezone)
    currency: str = Field(default_factory=lambda: get_settings().currency, min_length=3, max_length=3)
    scheduler_mode: SchedulerMode = SchedulerMode.RULE_BASED
    slot_minutes: int = Field(default=15, ge=5, le=60)
    horizon_hours: int = Field(default=24, ge=6, le=72)
    departure_buffer_minutes: int = Field(default=15, ge=0, le=120)
    urgent_window_hours: float = Field(default=3, ge=0.25, le=24)
    flex_slack_minutes: int = Field(default=60, ge=0, le=720)
    tariff_optimization: bool = True
    emergency_override: bool = True
    tie_breakers: list[Literal["departure", "soc", "created"]] = Field(default_factory=lambda: ["departure", "soc", "created"])
    required_soc_mode: Literal["operator", "rule"] = "operator"
    safety_reserve_type: Literal["percent", "kwh"] = "percent"
    safety_reserve_value: float = Field(default=10, ge=0, le=100)
    readiness_threshold_pct: float = Field(default=90, ge=0, le=100)
    readiness_window_hours: float = Field(default=24, ge=1, le=72)
    at_risk_warning_hours: float = Field(default=3, ge=0.25, le=24)
    missed_slot_grace_minutes: int = Field(default=15, ge=1, le=120)
    peak_warning_minutes: int = Field(default=30, ge=5, le=240)
    unexpected_consumption_pct: float = Field(default=20, ge=1, le=200)
    auto_recalc_minutes: int = Field(default=15, ge=1, le=240)
    require_schedule_approval: bool = False
    default_rate_per_kwh: float = Field(default=0.20, ge=0)
    simulation_enabled: bool = True
    clock_offset_seconds: float = Field(default=0, ge=0, le=60 * 60 * 24 * 14)
    v2g_enabled: bool = True
    v2g_soc_buffer: float = Field(default=15, ge=0, le=80)
    v2g_export_rate_per_kwh: float = Field(default=0.24, ge=0)
    v2g_min_dwell_hours: float = Field(default=2, ge=0.5, le=24)
    storage_round_trip_efficiency: float = Field(default=0.9, gt=0, le=1)
    webhook_url: str | None = Field(default=None, max_length=500)

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone '{v}'") from exc
        return v

    @field_validator("tie_breakers")
    @classmethod
    def _unique_tie_breakers(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v) or not v:
            raise ValueError("Tie-breakers must be a non-empty list without duplicates")
        return v

    @field_validator("webhook_url")
    @classmethod
    def _valid_webhook(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not v.startswith(("https://", "http://")):
            raise ValueError("Webhook URL must start with http:// or https://")
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


_cached: OperationalConfig | None = None


def load_config(db: Session) -> OperationalConfig:
    global _cached
    row = db.get(SystemConfig, CONFIG_KEY)
    _cached = OperationalConfig(**(row.value if row and isinstance(row.value, dict) else {}))
    return _cached


def cached_config() -> OperationalConfig:
    return _cached or OperationalConfig()


def save_config(db: Session, config: OperationalConfig, user_id: int | None) -> OperationalConfig:
    global _cached
    row = db.get(SystemConfig, CONFIG_KEY)
    payload = config.model_dump(mode="json")
    if row is None:
        db.add(SystemConfig(key=CONFIG_KEY, value=payload, updated_at=utcnow(), updated_by_id=user_id))
    else:
        row.value = payload
        row.updated_at = utcnow()
        row.updated_by_id = user_id
    _cached = config
    return config


def now() -> datetime:
    return (utcnow() + timedelta(seconds=cached_config().clock_offset_seconds)).replace(microsecond=0)


def as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
