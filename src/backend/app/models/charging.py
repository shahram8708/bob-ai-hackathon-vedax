from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, enum_type
from app.models.enums import (
    OPEN_REQUEST_STATUSES,
    RequestStatus,
    ReservationStatus,
    RunStatus,
    SchedulerMode,
    SessionSource,
    SessionStatus,
)
from app.models.fleet import Charger, Trip, Vehicle

_open_list = ", ".join(f"'{s.value}'" for s in OPEN_REQUEST_STATUSES)


class ScheduleRun(Base):
    __tablename__ = "schedule_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    planning_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trigger: Mapped[str] = mapped_column(String(80), nullable=False)
    mode: Mapped[SchedulerMode] = mapped_column(enum_type(SchedulerMode), nullable=False)
    status: Mapped[RunStatus] = mapped_column(enum_type(RunStatus), nullable=False)
    triggered_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    vehicles_evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vehicles_needing_charge: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reservations_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reservations_kept: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reservations_superseded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflicts_prevented: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    at_risk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    planned_energy_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    planned_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class ChargingRequest(TimestampMixin, Base):
    __tablename__ = "charging_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    trip_id: Mapped[int | None] = mapped_column(ForeignKey("trips.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("schedule_runs.id"))
    status: Mapped[RequestStatus] = mapped_column(enum_type(RequestStatus), nullable=False, index=True)
    priority_level: Mapped[int] = mapped_column(Integer, nullable=False)
    flexible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_soc: Mapped[float] = mapped_column(Float, nullable=False)
    target_soc: Mapped[float] = mapped_column(Float, nullable=False)
    required_soc: Mapped[float | None] = mapped_column(Float)
    energy_needed_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    projected_soc: Mapped[float | None] = mapped_column(Float)
    shortfall_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    rules: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    vehicle: Mapped[Vehicle] = relationship()
    trip: Mapped[Trip | None] = relationship()

    __table_args__ = (
        Index(
            "uq_open_request_per_vehicle",
            "vehicle_id",
            unique=True,
            postgresql_where=text(f"status IN ({_open_list})"),
        ),
    )


class ChargingSchedule(TimestampMixin, Base):
    __tablename__ = "charging_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("schedule_runs.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("charging_requests.id"))
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    charger_id: Mapped[int] = mapped_column(ForeignKey("chargers.id"), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    planned_energy_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    target_soc: Mapped[float] = mapped_column(Float, nullable=False)
    priority_level: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(enum_type(ReservationStatus), nullable=False, index=True)
    is_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_reason: Mapped[str | None] = mapped_column(String(500))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    rules: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tariff_mix: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    vehicle: Mapped[Vehicle] = relationship()
    charger: Mapped[Charger] = relationship()

    __table_args__ = (
        CheckConstraint("end_at > start_at", name="ck_schedule_window"),
        CheckConstraint("power_kw > 0", name="ck_schedule_power"),
        Index("ix_schedule_charger_window", "charger_id", "start_at", "end_at"),
    )


class ChargingSession(TimestampMixin, Base):
    __tablename__ = "charging_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("charging_schedules.id"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    charger_id: Mapped[int] = mapped_column(ForeignKey("chargers.id"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_soc: Mapped[float] = mapped_column(Float, nullable=False)
    end_soc: Mapped[float | None] = mapped_column(Float)
    target_soc: Mapped[float] = mapped_column(Float, nullable=False)
    power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    energy_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    tariff_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[SessionStatus] = mapped_column(enum_type(SessionStatus), nullable=False, index=True)
    stop_reason: Mapped[str | None] = mapped_column(String(160))
    source: Mapped[SessionSource] = mapped_column(enum_type(SessionSource), nullable=False)
    ocpp_transaction_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    meter_start_wh: Mapped[float | None] = mapped_column(Float)
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    vehicle: Mapped[Vehicle] = relationship()
    charger: Mapped[Charger] = relationship()
    schedule: Mapped[ChargingSchedule | None] = relationship()

    __table_args__ = (
        Index(
            "uq_active_session_per_charger",
            "charger_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_active_session_per_vehicle",
            "vehicle_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )


class EnergyReading(Base):
    __tablename__ = "energy_readings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("charging_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    charger_id: Mapped[int] = mapped_column(ForeignKey("chargers.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    energy_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    soc: Mapped[float | None] = mapped_column(Float)
    source: Mapped[SessionSource] = mapped_column(enum_type(SessionSource), nullable=False)
