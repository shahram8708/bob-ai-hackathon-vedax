from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import enum_type
from app.models.enums import AlertSeverity, AlertStatus, AlertType
from app.models.fleet import Charger, Vehicle


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[AlertType] = mapped_column(enum_type(AlertType), nullable=False, index=True)
    severity: Mapped[AlertSeverity] = mapped_column(enum_type(AlertSeverity), nullable=False)
    status: Mapped[AlertStatus] = mapped_column(enum_type(AlertStatus), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), index=True)
    charger_id: Mapped[int | None] = mapped_column(ForeignKey("chargers.id"))
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"))
    trip_id: Mapped[int | None] = mapped_column(ForeignKey("trips.id"))
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("charging_schedules.id"))
    dedup_key: Mapped[str | None] = mapped_column(String(160))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolution_note: Mapped[str | None] = mapped_column(Text)

    vehicle: Mapped[Vehicle | None] = relationship()
    charger: Mapped[Charger | None] = relationship()

    __table_args__ = (
        Index(
            "uq_alert_open_dedup",
            "dedup_key",
            unique=True,
            postgresql_where=text("dedup_key IS NOT NULL AND status <> 'resolved'"),
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor: Mapped[str] = mapped_column(String(160), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))


class ReadinessSnapshot(Base):
    __tablename__ = "readiness_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    vehicles_with_trip: Mapped[int] = mapped_column(Integer, nullable=False)
    ready_count: Mapped[int] = mapped_column(Integer, nullable=False)
    projected_ready_count: Mapped[int] = mapped_column(Integer, nullable=False)
    at_risk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    readiness_pct: Mapped[float] = mapped_column(Float, nullable=False)


class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
