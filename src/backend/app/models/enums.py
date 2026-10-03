from enum import StrEnum


class RoleCode(StrEnum):
    ADMIN = "admin"
    FLEET_MANAGER = "fleet_manager"
    OPERATIONS_MANAGER = "operations_manager"
    CHARGING_OPERATOR = "charging_operator"
    DRIVER = "driver"
    VIEWER = "viewer"


class VehicleAvailability(StrEnum):
    AVAILABLE = "available"
    CHARGING = "charging"
    ON_TRIP = "on_trip"
    MAINTENANCE = "maintenance"
    OUT_OF_SERVICE = "out_of_service"


class VehiclePriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    STANDARD = "standard"
    LOW = "low"


class TripPriority(StrEnum):
    EMERGENCY = "emergency"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class TripStatus(StrEnum):
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ChargerStatus(StrEnum):
    AVAILABLE = "available"
    CHARGING = "charging"
    RESERVED = "reserved"
    FAULT = "fault"
    MAINTENANCE = "maintenance"


class TariffKind(StrEnum):
    PEAK = "peak"
    SHOULDER = "shoulder"
    OFF_PEAK = "off_peak"
    CUSTOM = "custom"


class RequestStatus(StrEnum):
    SCHEDULED = "scheduled"
    AT_RISK = "at_risk"
    UNSCHEDULED = "unscheduled"
    SATISFIED = "satisfied"
    FULFILLED = "fulfilled"
    MET = "met"
    MISSED = "missed"
    CANCELLED = "cancelled"


OPEN_REQUEST_STATUSES = (RequestStatus.SCHEDULED, RequestStatus.AT_RISK, RequestStatus.UNSCHEDULED)


class ReservationStatus(StrEnum):
    PROPOSED = "proposed"
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    MISSED = "missed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    INTERRUPTED = "interrupted"


class RunStatus(StrEnum):
    APPLIED = "applied"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class SchedulerMode(StrEnum):
    BASELINE = "baseline"
    RULE_BASED = "rule_based"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    STOPPED = "stopped"
    INTERRUPTED = "interrupted"


class SessionSource(StrEnum):
    SIMULATED = "simulated"
    OCPP = "ocpp"
    MANUAL = "manual"


class AlertType(StrEnum):
    BELOW_REQUIRED_SOC = "below_required_soc"
    SESSION_INTERRUPTED = "session_interrupted"
    CHARGER_FAULT = "charger_fault"
    MISSED_SLOT = "missed_slot"
    RESERVATION_CONFLICT = "reservation_conflict"
    UNEXPECTED_CONSUMPTION = "unexpected_consumption"
    PEAK_APPROACHING = "peak_approaching"
    READINESS_BELOW_THRESHOLD = "readiness_below_threshold"
    DEPARTED_BELOW_REQUIRED = "departed_below_required"
    MANUAL_EXCEPTION = "manual_exception"


class AlertSeverity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class ProviderKind(StrEnum):
    PUBLIC_CHARGING = "public_charging"
    MOBILE_CHARGING = "mobile_charging"
    TOWING = "towing"
