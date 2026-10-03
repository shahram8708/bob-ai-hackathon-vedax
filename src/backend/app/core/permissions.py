from enum import StrEnum

from app.models.enums import RoleCode


class Perm(StrEnum):
    VIEW_DASHBOARD = "dashboard:view"
    VIEW_FLEET = "fleet:view"
    MANAGE_VEHICLES = "vehicles:manage"
    VEHICLE_EVENTS = "vehicles:events"
    MANAGE_TRIPS = "trips:manage"
    MANAGE_DRIVERS = "drivers:manage"
    MANAGE_INFRASTRUCTURE = "infrastructure:manage"
    CHARGER_STATE = "chargers:state"
    MANAGE_TARIFFS = "tariffs:manage"
    RUN_SCHEDULER = "schedule:run"
    APPROVE_SCHEDULE = "schedule:approve"
    OVERRIDE_SCHEDULE = "schedule:override"
    MANAGE_SESSIONS = "sessions:manage"
    MANAGE_ALERTS = "alerts:manage"
    VIEW_REPORTS = "reports:view"
    VIEW_AUDIT = "audit:view"
    MANAGE_USERS = "users:manage"
    MANAGE_CONFIG = "config:manage"
    CONTROL_SIMULATION = "simulation:control"
    VIEW_OWN_VEHICLE = "driver:self"


_MONITOR = {Perm.VIEW_DASHBOARD, Perm.VIEW_FLEET, Perm.VIEW_REPORTS}

ROLE_PERMISSIONS: dict[RoleCode, frozenset[Perm]] = {
    RoleCode.ADMIN: frozenset(p for p in Perm if p is not Perm.VIEW_OWN_VEHICLE),
    RoleCode.FLEET_MANAGER: frozenset(
        _MONITOR
        | {
            Perm.VEHICLE_EVENTS,
            Perm.MANAGE_TRIPS,
            Perm.CHARGER_STATE,
            Perm.RUN_SCHEDULER,
            Perm.APPROVE_SCHEDULE,
            Perm.OVERRIDE_SCHEDULE,
            Perm.MANAGE_SESSIONS,
            Perm.MANAGE_ALERTS,
            Perm.VIEW_AUDIT,
            Perm.CONTROL_SIMULATION,
        }
    ),
    RoleCode.OPERATIONS_MANAGER: frozenset(
        _MONITOR | {Perm.VEHICLE_EVENTS, Perm.MANAGE_TRIPS, Perm.MANAGE_DRIVERS, Perm.RUN_SCHEDULER, Perm.MANAGE_ALERTS}
    ),
    RoleCode.CHARGING_OPERATOR: frozenset(
        _MONITOR
        | {Perm.VEHICLE_EVENTS, Perm.CHARGER_STATE, Perm.OVERRIDE_SCHEDULE, Perm.MANAGE_SESSIONS, Perm.MANAGE_ALERTS}
    ),
    RoleCode.DRIVER: frozenset({Perm.VIEW_OWN_VEHICLE}),
    RoleCode.VIEWER: frozenset(_MONITOR),
}

ROLE_INFO: dict[RoleCode, tuple[str, str]] = {
    RoleCode.ADMIN: ("Fleet Administrator", "Manages vehicles, chargers, users, tariff settings and operational rules."),
    RoleCode.FLEET_MANAGER: ("Fleet Manager", "Monitors readiness, approves schedules, handles exceptions and reviews reports."),
    RoleCode.OPERATIONS_MANAGER: ("Operations Manager", "Manages trips, departures and vehicle assignments."),
    RoleCode.CHARGING_OPERATOR: ("Charging Operator", "Monitors charger status and charging sessions."),
    RoleCode.DRIVER: ("Driver", "Views assigned vehicle, current SoC, required SoC and charging instructions."),
    RoleCode.VIEWER: ("Viewer / Management", "Accesses dashboards and reports without operational write access."),
}


def permissions_for(role: str) -> frozenset[Perm]:
    try:
        return ROLE_PERMISSIONS[RoleCode(role)]
    except ValueError:
        return frozenset()
