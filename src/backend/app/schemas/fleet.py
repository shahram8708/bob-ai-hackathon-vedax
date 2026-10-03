import re
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    ChargerStatus,
    TariffKind,
    TripPriority,
    TripStatus,
    VehicleAvailability,
    VehiclePriority,
)

CONNECTORS = ("CCS2", "Type2", "CHAdeMO", "GB/T")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_CODE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _aware(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is None:
        raise ValueError("Datetime must include a timezone offset")
    return v


def _code(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip().upper()
    if not _CODE.match(v):
        raise ValueError("Use 2–32 letters, digits or hyphens")
    return v


class StationIn(Strict):
    code: str
    name: str = Field(min_length=2, max_length=120)
    address: str = Field(default="", max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    max_load_kw: float | None = Field(default=None, gt=0, le=20000)
    solar_capacity_kw: float = Field(default=0, ge=0, le=10000)
    battery_capacity_kwh: float = Field(default=0, ge=0, le=50000)
    battery_power_kw: float = Field(default=0, ge=0, le=20000)
    is_active: bool = True

    _c = field_validator("code")(_code)


class StationPatch(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    address: str | None = Field(default=None, max_length=255)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    max_load_kw: float | None = Field(default=None, gt=0, le=20000)
    solar_capacity_kw: float | None = Field(default=None, ge=0, le=10000)
    battery_capacity_kwh: float | None = Field(default=None, ge=0, le=50000)
    battery_power_kw: float | None = Field(default=None, ge=0, le=20000)
    is_active: bool | None = None


class VehicleIn(Strict):
    registration: str
    vehicle_type: str | None = Field(default=None, max_length=60)
    battery_profile_id: int
    battery_capacity_kwh: float | None = Field(default=None, gt=0, le=1500)
    current_soc: float = Field(ge=0, le=100)
    min_operating_soc: float = Field(default=20, ge=0, le=100)
    required_departure_soc: float = Field(default=80, gt=0, le=100)
    max_soc: float = Field(default=90, gt=0, le=100)
    home_station_id: int
    priority_category: VehiclePriority = VehiclePriority.STANDARD
    assigned_driver_id: int | None = None
    notes: str = Field(default="", max_length=2000)
    external_ref: str | None = Field(default=None, max_length=64)

    _r = field_validator("registration")(_code)

    @model_validator(mode="after")
    def _bounds(self):
        if not self.min_operating_soc <= self.required_departure_soc <= self.max_soc:
            raise ValueError("SoC limits must satisfy minimum ≤ required departure ≤ maximum")
        return self


class VehiclePatch(Strict):
    vehicle_type: str | None = Field(default=None, max_length=60)
    battery_profile_id: int | None = None
    battery_capacity_kwh: float | None = Field(default=None, gt=0, le=1500)
    min_operating_soc: float | None = Field(default=None, ge=0, le=100)
    required_departure_soc: float | None = Field(default=None, gt=0, le=100)
    max_soc: float | None = Field(default=None, gt=0, le=100)
    home_station_id: int | None = None
    priority_category: VehiclePriority | None = None
    assigned_driver_id: int | None = None
    availability: VehicleAvailability | None = None
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    clear_driver: bool = False
    clear_hold: bool = False


class SocUpdate(Strict):
    soc: float = Field(ge=0, le=100)


class ArriveIn(Strict):
    station_id: int
    soc: float | None = Field(default=None, ge=0, le=100)


class DepartIn(Strict):
    trip_id: int | None = None


class DriverIn(Strict):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(default="", max_length=32, pattern=r"^[0-9+\-() ]*$")
    license_number: str = Field(min_length=4, max_length=40)
    home_station_id: int | None = None
    user_id: int | None = None
    is_active: bool = True


class DriverPatch(Strict):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=32, pattern=r"^[0-9+\-() ]*$")
    license_number: str | None = Field(default=None, min_length=4, max_length=40)
    home_station_id: int | None = None
    user_id: int | None = None
    is_active: bool | None = None


class TripIn(Strict):
    code: str | None = None
    vehicle_id: int | None = None
    driver_id: int | None = None
    origin_station_id: int
    destination: str = Field(min_length=2, max_length=160)
    destination_latitude: float | None = Field(default=None, ge=-90, le=90)
    destination_longitude: float | None = Field(default=None, ge=-180, le=180)
    distance_km: float = Field(ge=0, le=2000)
    energy_kwh: float | None = Field(default=None, ge=0, le=2000)
    required_soc: float | None = Field(default=None, gt=0, le=100)
    departure_at: datetime
    return_at: datetime | None = None
    priority: TripPriority = TripPriority.NORMAL
    external_ref: str | None = Field(default=None, max_length=64)

    _c = field_validator("code")(_code)
    _a = field_validator("departure_at", "return_at")(_aware)

    @model_validator(mode="after")
    def _times(self):
        if self.return_at and self.return_at <= self.departure_at:
            raise ValueError("Return time must be after departure time")
        return self


class TripPatch(Strict):
    vehicle_id: int | None = None
    driver_id: int | None = None
    destination: str | None = Field(default=None, min_length=2, max_length=160)
    distance_km: float | None = Field(default=None, ge=0, le=2000)
    energy_kwh: float | None = Field(default=None, ge=0, le=2000)
    required_soc: float | None = Field(default=None, gt=0, le=100)
    departure_at: datetime | None = None
    return_at: datetime | None = None
    priority: TripPriority | None = None
    status: TripStatus | None = None
    unassign: bool = False

    _a = field_validator("departure_at", "return_at")(_aware)


class CompleteTripIn(Strict):
    arrival_soc: float = Field(ge=0, le=100)
    station_id: int | None = None


class AvailabilityWindow(Strict):
    days: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("Use HH:MM (24h)")
        return v

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("Days are 0 (Mon) to 6 (Sun)")
        return sorted(set(v))


class ChargerIn(Strict):
    code: str
    station_id: int
    connector_type: str
    max_power_kw: float = Field(gt=0, le=500)
    availability_schedule: list[AvailabilityWindow] | None = None
    bidirectional: bool = False
    ocpp_identity: str | None = Field(default=None, max_length=48, pattern=r"^[A-Za-z0-9_\-]+$")
    is_active: bool = True

    _c = field_validator("code")(_code)

    @field_validator("connector_type")
    @classmethod
    def _conn(cls, v: str) -> str:
        if v not in CONNECTORS:
            raise ValueError(f"Connector must be one of {', '.join(CONNECTORS)}")
        return v


class ChargerPatch(Strict):
    connector_type: str | None = None
    max_power_kw: float | None = Field(default=None, gt=0, le=500)
    availability_schedule: list[AvailabilityWindow] | None = None
    clear_availability_schedule: bool = False
    bidirectional: bool | None = None
    ocpp_identity: str | None = Field(default=None, max_length=48, pattern=r"^[A-Za-z0-9_\-]+$")
    is_active: bool | None = None

    @field_validator("connector_type")
    @classmethod
    def _conn(cls, v: str | None) -> str | None:
        if v is not None and v not in CONNECTORS:
            raise ValueError(f"Connector must be one of {', '.join(CONNECTORS)}")
        return v


class ChargerStatusIn(Strict):
    status: ChargerStatus
    note: str = Field(default="", max_length=255)


class PowerLimitIn(Strict):
    limit_kw: float | None = Field(default=None, gt=0, le=500)


class TariffIn(Strict):
    name: str = Field(min_length=2, max_length=80)
    kind: TariffKind
    start_time: time
    end_time: time
    rate_per_kwh: float = Field(ge=0, le=1000)
    demand_charge_per_kw: float | None = Field(default=None, ge=0, le=100000)
    days_of_week: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    station_id: int | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def _window(self):
        if self.start_time == self.end_time:
            raise ValueError("Start and end time must differ")
        if any(d < 0 or d > 6 for d in self.days_of_week):
            raise ValueError("Days are 0 (Mon) to 6 (Sun)")
        self.days_of_week = sorted(set(self.days_of_week))
        return self


class PriceSignalIn(Strict):
    starts_at: datetime
    ends_at: datetime
    rate_per_kwh: float = Field(ge=0, le=1000)
    station_id: int | None = None

    _a = field_validator("starts_at", "ends_at")(_aware)

    @model_validator(mode="after")
    def _window(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class PriceFeedIn(Strict):
    source: str = Field(default="Utility price feed", min_length=2, max_length=60)
    replace_window: bool = True
    signals: list[PriceSignalIn] = Field(min_length=1, max_length=2000)


class ServiceProviderIn(Strict):
    name: str = Field(min_length=2, max_length=120)
    kind: str = Field(pattern="^(public_charging|mobile_charging|towing)$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    phone: str = Field(default="", max_length=32)
    connector_types: list[str] = Field(default_factory=list)
    max_power_kw: float | None = Field(default=None, gt=0)
    rate_per_kwh: float | None = Field(default=None, ge=0)
    callout_fee: float | None = Field(default=None, ge=0)
    per_km_fee: float | None = Field(default=None, ge=0)
    avg_response_min: int | None = Field(default=None, ge=0, le=1440)
