from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, enum_type
from app.models.enums import (
    ChargerStatus,
    ProviderKind,
    TariffKind,
    TripPriority,
    TripStatus,
    VehicleAvailability,
    VehiclePriority,
)


class Station(TimestampMixin, Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    max_load_kw: Mapped[float | None] = mapped_column(Float)
    solar_capacity_kw: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    battery_capacity_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    battery_power_kw: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    chargers: Mapped[list["Charger"]] = relationship(back_populates="station", order_by="Charger.code")

    __table_args__ = (
        CheckConstraint("max_load_kw IS NULL OR max_load_kw > 0", name="ck_station_load_positive"),
        CheckConstraint("solar_capacity_kw >= 0 AND battery_capacity_kwh >= 0 AND battery_power_kw >= 0", name="ck_station_assets"),
    )


class BatteryProfile(Base):
    __tablename__ = "battery_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(60), nullable=False)
    capacity_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    max_ac_kw: Mapped[float] = mapped_column(Float, nullable=False)
    max_dc_kw: Mapped[float] = mapped_column(Float, nullable=False)
    charging_efficiency: Mapped[float] = mapped_column(Float, nullable=False, default=0.92)
    consumption_kwh_per_km: Mapped[float] = mapped_column(Float, nullable=False)
    connector_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        CheckConstraint("capacity_kwh > 0", name="ck_profile_capacity"),
        CheckConstraint("charging_efficiency > 0 AND charging_efficiency <= 1", name="ck_profile_efficiency"),
    )


class Driver(TimestampMixin, Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    license_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    home_station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    external_ref: Mapped[str | None] = mapped_column(String(64), unique=True)

    user: Mapped["User | None"] = relationship(back_populates="driver")  # noqa: F821
    home_station: Mapped[Station | None] = relationship()


class Vehicle(TimestampMixin, Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    registration: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(60), nullable=False)
    battery_profile_id: Mapped[int] = mapped_column(ForeignKey("battery_profiles.id"), nullable=False)
    battery_capacity_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    current_soc: Mapped[float] = mapped_column(Float, nullable=False)
    min_operating_soc: Mapped[float] = mapped_column(Float, nullable=False, default=20)
    required_departure_soc: Mapped[float] = mapped_column(Float, nullable=False, default=80)
    max_soc: Mapped[float] = mapped_column(Float, nullable=False, default=90)
    home_station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), nullable=False)
    current_station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    availability: Mapped[VehicleAvailability] = mapped_column(
        enum_type(VehicleAvailability), nullable=False, default=VehicleAvailability.AVAILABLE, index=True
    )
    priority_category: Mapped[VehiclePriority] = mapped_column(
        enum_type(VehiclePriority), nullable=False, default=VehiclePriority.STANDARD
    )
    assigned_driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    soc_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    charging_hold_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_ref: Mapped[str | None] = mapped_column(String(64), unique=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    battery_profile: Mapped[BatteryProfile] = relationship(lazy="joined")
    home_station: Mapped[Station] = relationship(foreign_keys=[home_station_id])
    current_station: Mapped[Station | None] = relationship(foreign_keys=[current_station_id])
    assigned_driver: Mapped[Driver | None] = relationship()

    __table_args__ = (
        CheckConstraint("current_soc >= 0 AND current_soc <= 100", name="ck_vehicle_soc"),
        CheckConstraint(
            "min_operating_soc >= 0 AND min_operating_soc <= required_departure_soc AND required_departure_soc <= max_soc AND max_soc <= 100",
            name="ck_vehicle_soc_bounds",
        ),
        CheckConstraint("battery_capacity_kwh > 0", name="ck_vehicle_capacity"),
    )


class Trip(TimestampMixin, Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), index=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"))
    origin_station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), nullable=False)
    destination: Mapped[str] = mapped_column(String(160), nullable=False)
    destination_latitude: Mapped[float | None] = mapped_column(Float)
    destination_longitude: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    energy_kwh: Mapped[float | None] = mapped_column(Float)
    required_soc: Mapped[float | None] = mapped_column(Float)
    departure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    return_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[TripPriority] = mapped_column(enum_type(TripPriority), nullable=False, default=TripPriority.NORMAL)
    status: Mapped[TripStatus] = mapped_column(enum_type(TripStatus), nullable=False, default=TripStatus.UNASSIGNED, index=True)
    departed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    departure_soc: Mapped[float | None] = mapped_column(Float)
    requirement_met: Mapped[bool | None] = mapped_column(Boolean)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrival_soc: Mapped[float | None] = mapped_column(Float)
    actual_energy_kwh: Mapped[float | None] = mapped_column(Float)
    external_ref: Mapped[str | None] = mapped_column(String(64), unique=True)

    vehicle: Mapped[Vehicle | None] = relationship()
    driver: Mapped[Driver | None] = relationship()
    origin_station: Mapped[Station] = relationship()

    __table_args__ = (
        CheckConstraint("distance_km >= 0", name="ck_trip_distance"),
        CheckConstraint("required_soc IS NULL OR (required_soc > 0 AND required_soc <= 100)", name="ck_trip_required_soc"),
        CheckConstraint("energy_kwh IS NULL OR energy_kwh >= 0", name="ck_trip_energy"),
        CheckConstraint("return_at IS NULL OR return_at > departure_at", name="ck_trip_return_after_departure"),
    )


class Charger(TimestampMixin, Base):
    __tablename__ = "chargers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), nullable=False, index=True)
    connector_type: Mapped[str] = mapped_column(String(24), nullable=False)
    max_power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    power_limit_kw: Mapped[float | None] = mapped_column(Float)
    status: Mapped[ChargerStatus] = mapped_column(enum_type(ChargerStatus), nullable=False, default=ChargerStatus.AVAILABLE)
    current_vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"))
    availability_schedule: Mapped[list[dict] | None] = mapped_column(JSONB)
    bidirectional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ocpp_identity: Mapped[str | None] = mapped_column(String(48), unique=True)
    ocpp_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    station: Mapped[Station] = relationship(back_populates="chargers")
    current_vehicle: Mapped[Vehicle | None] = relationship()

    __table_args__ = (
        CheckConstraint("max_power_kw > 0", name="ck_charger_power"),
        CheckConstraint("power_limit_kw IS NULL OR power_limit_kw > 0", name="ck_charger_power_limit"),
    )

    @property
    def effective_power_kw(self) -> float:
        return min(self.max_power_kw, self.power_limit_kw or self.max_power_kw)


class TariffPeriod(TimestampMixin, Base):
    __tablename__ = "tariff_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[TariffKind] = mapped_column(enum_type(TariffKind), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    rate_per_kwh: Mapped[float] = mapped_column(Numeric(10, 4, asdecimal=False), nullable=False)
    demand_charge_per_kw: Mapped[float | None] = mapped_column(Numeric(10, 4, asdecimal=False))
    days_of_week: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=lambda: list(range(7)))
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    station: Mapped[Station | None] = relationship()

    __table_args__ = (
        CheckConstraint("rate_per_kwh >= 0", name="ck_tariff_rate"),
        CheckConstraint("demand_charge_per_kw IS NULL OR demand_charge_per_kw >= 0", name="ck_tariff_demand"),
        CheckConstraint("start_time <> end_time", name="ck_tariff_window"),
    )


class PriceSignal(Base):
    __tablename__ = "price_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rate_per_kwh: Mapped[float] = mapped_column(Numeric(10, 4, asdecimal=False), nullable=False)
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_price_signal_window"),
        CheckConstraint("rate_per_kwh >= 0", name="ck_price_signal_rate"),
    )


class ServiceProvider(Base):
    __tablename__ = "service_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[ProviderKind] = mapped_column(enum_type(ProviderKind), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    connector_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    max_power_kw: Mapped[float | None] = mapped_column(Float)
    rate_per_kwh: Mapped[float | None] = mapped_column(Float)
    callout_fee: Mapped[float | None] = mapped_column(Float)
    per_km_fee: Mapped[float | None] = mapped_column(Float)
    avg_response_min: Mapped[int | None] = mapped_column(Integer)
    is_directory_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
