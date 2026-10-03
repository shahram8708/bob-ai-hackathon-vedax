"""initial_schema

Revision ID: 0001
Revises:
Create Date: 2026-10-03 11:08:34.875480
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table('battery_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('vehicle_type', sa.String(length=60), nullable=False),
    sa.Column('capacity_kwh', sa.Float(), nullable=False),
    sa.Column('max_ac_kw', sa.Float(), nullable=False),
    sa.Column('max_dc_kw', sa.Float(), nullable=False),
    sa.Column('charging_efficiency', sa.Float(), nullable=False),
    sa.Column('consumption_kwh_per_km', sa.Float(), nullable=False),
    sa.Column('connector_types', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint('capacity_kwh > 0', name='ck_profile_capacity'),
    sa.CheckConstraint('charging_efficiency > 0 AND charging_efficiency <= 1', name='ck_profile_efficiency'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('readiness_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('vehicles_with_trip', sa.Integer(), nullable=False),
    sa.Column('ready_count', sa.Integer(), nullable=False),
    sa.Column('projected_ready_count', sa.Integer(), nullable=False),
    sa.Column('at_risk_count', sa.Integer(), nullable=False),
    sa.Column('readiness_pct', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_readiness_snapshots_recorded_at'), 'readiness_snapshots', ['recorded_at'], unique=False)
    op.create_table('roles',
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('permissions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_table('service_providers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('kind', sa.Enum('public_charging', 'mobile_charging', 'towing', name='ck_providerkind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=False),
    sa.Column('connector_types', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('max_power_kw', sa.Float(), nullable=True),
    sa.Column('rate_per_kwh', sa.Float(), nullable=True),
    sa.Column('callout_fee', sa.Float(), nullable=True),
    sa.Column('per_km_fee', sa.Float(), nullable=True),
    sa.Column('avg_response_min', sa.Integer(), nullable=True),
    sa.Column('is_directory_sample', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('stations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('address', sa.String(length=255), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('max_load_kw', sa.Float(), nullable=True),
    sa.Column('solar_capacity_kw', sa.Float(), nullable=False),
    sa.Column('battery_capacity_kwh', sa.Float(), nullable=False),
    sa.Column('battery_power_kw', sa.Float(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('max_load_kw IS NULL OR max_load_kw > 0', name='ck_station_load_positive'),
    sa.CheckConstraint('solar_capacity_kw >= 0 AND battery_capacity_kwh >= 0 AND battery_power_kw >= 0', name='ck_station_assets'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('price_signals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('station_id', sa.Integer(), nullable=True),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('rate_per_kwh', sa.Numeric(precision=10, scale=4, asdecimal=False), nullable=False),
    sa.Column('source', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('ends_at > starts_at', name='ck_price_signal_window'),
    sa.CheckConstraint('rate_per_kwh >= 0', name='ck_price_signal_rate'),
    sa.ForeignKeyConstraint(['station_id'], ['stations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_price_signals_starts_at'), 'price_signals', ['starts_at'], unique=False)
    op.create_table('tariff_periods',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('kind', sa.Enum('peak', 'shoulder', 'off_peak', 'custom', name='ck_tariffkind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.Column('rate_per_kwh', sa.Numeric(precision=10, scale=4, asdecimal=False), nullable=False),
    sa.Column('demand_charge_per_kw', sa.Numeric(precision=10, scale=4, asdecimal=False), nullable=True),
    sa.Column('days_of_week', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('station_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('demand_charge_per_kw IS NULL OR demand_charge_per_kw >= 0', name='ck_tariff_demand'),
    sa.CheckConstraint('rate_per_kwh >= 0', name='ck_tariff_rate'),
    sa.CheckConstraint('start_time <> end_time', name='ck_tariff_window'),
    sa.ForeignKeyConstraint(['station_id'], ['stations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('role_code', sa.String(length=32), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['role_code'], ['roles.code'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_role_code'), 'users', ['role_code'], unique=False)
    op.create_table('audit_logs',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('actor', sa.String(length=160), nullable=False),
    sa.Column('action', sa.String(length=80), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('entity_type', sa.String(length=40), nullable=True),
    sa.Column('entity_id', sa.String(length=40), nullable=True),
    sa.Column('summary', sa.String(length=500), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_category'), 'audit_logs', ['category'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_table('drivers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=False),
    sa.Column('license_number', sa.String(length=40), nullable=False),
    sa.Column('home_station_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('external_ref', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['home_station_id'], ['stations.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('external_ref'),
    sa.UniqueConstraint('license_number'),
    sa.UniqueConstraint('user_id')
    )
    op.create_table('schedule_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('planning_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('trigger', sa.String(length=80), nullable=False),
    sa.Column('mode', sa.Enum('baseline', 'rule_based', name='ck_schedulermode', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('applied', 'pending_approval', 'approved', 'rejected', name='ck_runstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('triggered_by_id', sa.Integer(), nullable=True),
    sa.Column('approved_by_id', sa.Integer(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_ms', sa.Float(), nullable=False),
    sa.Column('vehicles_evaluated', sa.Integer(), nullable=False),
    sa.Column('vehicles_needing_charge', sa.Integer(), nullable=False),
    sa.Column('reservations_created', sa.Integer(), nullable=False),
    sa.Column('reservations_kept', sa.Integer(), nullable=False),
    sa.Column('reservations_superseded', sa.Integer(), nullable=False),
    sa.Column('conflicts_prevented', sa.Integer(), nullable=False),
    sa.Column('at_risk_count', sa.Integer(), nullable=False),
    sa.Column('planned_energy_kwh', sa.Float(), nullable=False),
    sa.Column('planned_cost', sa.Float(), nullable=False),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['approved_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['triggered_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_schedule_runs_created_at'), 'schedule_runs', ['created_at'], unique=False)
    op.create_table('system_config',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('vehicles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('registration', sa.String(length=32), nullable=False),
    sa.Column('vehicle_type', sa.String(length=60), nullable=False),
    sa.Column('battery_profile_id', sa.Integer(), nullable=False),
    sa.Column('battery_capacity_kwh', sa.Float(), nullable=False),
    sa.Column('current_soc', sa.Float(), nullable=False),
    sa.Column('min_operating_soc', sa.Float(), nullable=False),
    sa.Column('required_departure_soc', sa.Float(), nullable=False),
    sa.Column('max_soc', sa.Float(), nullable=False),
    sa.Column('home_station_id', sa.Integer(), nullable=False),
    sa.Column('current_station_id', sa.Integer(), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('availability', sa.Enum('available', 'charging', 'on_trip', 'maintenance', 'out_of_service', name='ck_vehicleavailability', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('priority_category', sa.Enum('critical', 'high', 'standard', 'low', name='ck_vehiclepriority', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('assigned_driver_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('soc_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('charging_hold_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('external_ref', sa.String(length=64), nullable=True),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('battery_capacity_kwh > 0', name='ck_vehicle_capacity'),
    sa.CheckConstraint('current_soc >= 0 AND current_soc <= 100', name='ck_vehicle_soc'),
    sa.CheckConstraint('min_operating_soc >= 0 AND min_operating_soc <= required_departure_soc AND required_departure_soc <= max_soc AND max_soc <= 100', name='ck_vehicle_soc_bounds'),
    sa.ForeignKeyConstraint(['assigned_driver_id'], ['drivers.id'], ),
    sa.ForeignKeyConstraint(['battery_profile_id'], ['battery_profiles.id'], ),
    sa.ForeignKeyConstraint(['current_station_id'], ['stations.id'], ),
    sa.ForeignKeyConstraint(['home_station_id'], ['stations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('external_ref')
    )
    op.create_index(op.f('ix_vehicles_availability'), 'vehicles', ['availability'], unique=False)
    op.create_index(op.f('ix_vehicles_is_active'), 'vehicles', ['is_active'], unique=False)
    op.create_index(op.f('ix_vehicles_registration'), 'vehicles', ['registration'], unique=True)
    op.create_table('chargers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=24), nullable=False),
    sa.Column('station_id', sa.Integer(), nullable=False),
    sa.Column('connector_type', sa.String(length=24), nullable=False),
    sa.Column('max_power_kw', sa.Float(), nullable=False),
    sa.Column('power_limit_kw', sa.Float(), nullable=True),
    sa.Column('status', sa.Enum('available', 'charging', 'reserved', 'fault', 'maintenance', name='ck_chargerstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('current_vehicle_id', sa.Integer(), nullable=True),
    sa.Column('availability_schedule', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('bidirectional', sa.Boolean(), nullable=False),
    sa.Column('ocpp_identity', sa.String(length=48), nullable=True),
    sa.Column('ocpp_connected', sa.Boolean(), nullable=False),
    sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status_note', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('max_power_kw > 0', name='ck_charger_power'),
    sa.CheckConstraint('power_limit_kw IS NULL OR power_limit_kw > 0', name='ck_charger_power_limit'),
    sa.ForeignKeyConstraint(['current_vehicle_id'], ['vehicles.id'], ),
    sa.ForeignKeyConstraint(['station_id'], ['stations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    sa.UniqueConstraint('ocpp_identity')
    )
    op.create_index(op.f('ix_chargers_station_id'), 'chargers', ['station_id'], unique=False)
    op.create_table('trips',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=24), nullable=False),
    sa.Column('vehicle_id', sa.Integer(), nullable=True),
    sa.Column('driver_id', sa.Integer(), nullable=True),
    sa.Column('origin_station_id', sa.Integer(), nullable=False),
    sa.Column('destination', sa.String(length=160), nullable=False),
    sa.Column('destination_latitude', sa.Float(), nullable=True),
    sa.Column('destination_longitude', sa.Float(), nullable=True),
    sa.Column('distance_km', sa.Float(), nullable=False),
    sa.Column('energy_kwh', sa.Float(), nullable=True),
    sa.Column('required_soc', sa.Float(), nullable=True),
    sa.Column('departure_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('return_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('priority', sa.Enum('emergency', 'high', 'normal', 'low', name='ck_trippriority', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('unassigned', 'assigned', 'in_progress', 'completed', 'cancelled', name='ck_tripstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('departed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('departure_soc', sa.Float(), nullable=True),
    sa.Column('requirement_met', sa.Boolean(), nullable=True),
    sa.Column('arrived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('arrival_soc', sa.Float(), nullable=True),
    sa.Column('actual_energy_kwh', sa.Float(), nullable=True),
    sa.Column('external_ref', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('distance_km >= 0', name='ck_trip_distance'),
    sa.CheckConstraint('energy_kwh IS NULL OR energy_kwh >= 0', name='ck_trip_energy'),
    sa.CheckConstraint('required_soc IS NULL OR (required_soc > 0 AND required_soc <= 100)', name='ck_trip_required_soc'),
    sa.CheckConstraint('return_at IS NULL OR return_at > departure_at', name='ck_trip_return_after_departure'),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ),
    sa.ForeignKeyConstraint(['origin_station_id'], ['stations.id'], ),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    sa.UniqueConstraint('external_ref')
    )
    op.create_index(op.f('ix_trips_departure_at'), 'trips', ['departure_at'], unique=False)
    op.create_index(op.f('ix_trips_status'), 'trips', ['status'], unique=False)
    op.create_index(op.f('ix_trips_vehicle_id'), 'trips', ['vehicle_id'], unique=False)
    op.create_table('charging_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('vehicle_id', sa.Integer(), nullable=False),
    sa.Column('trip_id', sa.Integer(), nullable=True),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.Enum('scheduled', 'at_risk', 'unscheduled', 'satisfied', 'fulfilled', 'met', 'missed', 'cancelled', name='ck_requeststatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('priority_level', sa.Integer(), nullable=False),
    sa.Column('flexible', sa.Boolean(), nullable=False),
    sa.Column('current_soc', sa.Float(), nullable=False),
    sa.Column('target_soc', sa.Float(), nullable=False),
    sa.Column('required_soc', sa.Float(), nullable=True),
    sa.Column('energy_needed_kwh', sa.Float(), nullable=False),
    sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('projected_soc', sa.Float(), nullable=True),
    sa.Column('shortfall_kwh', sa.Float(), nullable=False),
    sa.Column('rules', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['schedule_runs.id'], ),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_charging_requests_status'), 'charging_requests', ['status'], unique=False)
    op.create_index(op.f('ix_charging_requests_trip_id'), 'charging_requests', ['trip_id'], unique=False)
    op.create_index(op.f('ix_charging_requests_vehicle_id'), 'charging_requests', ['vehicle_id'], unique=False)
    op.create_index('uq_open_request_per_vehicle', 'charging_requests', ['vehicle_id'], unique=True, postgresql_where=sa.text("status IN ('scheduled', 'at_risk', 'unscheduled')"))
    op.create_table('charging_schedules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('request_id', sa.Integer(), nullable=True),
    sa.Column('vehicle_id', sa.Integer(), nullable=False),
    sa.Column('charger_id', sa.Integer(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('power_kw', sa.Float(), nullable=False),
    sa.Column('planned_energy_kwh', sa.Float(), nullable=False),
    sa.Column('estimated_cost', sa.Float(), nullable=False),
    sa.Column('target_soc', sa.Float(), nullable=False),
    sa.Column('priority_level', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('proposed', 'planned', 'active', 'completed', 'missed', 'cancelled', 'superseded', 'interrupted', name='ck_reservationstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('is_override', sa.Boolean(), nullable=False),
    sa.Column('override_reason', sa.String(length=500), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('rules', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('tariff_mix', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('end_at > start_at', name='ck_schedule_window'),
    sa.CheckConstraint('power_kw > 0', name='ck_schedule_power'),
    sa.ForeignKeyConstraint(['charger_id'], ['chargers.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['charging_requests.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['schedule_runs.id'], ),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_charging_schedules_run_id'), 'charging_schedules', ['run_id'], unique=False)
    op.create_index(op.f('ix_charging_schedules_status'), 'charging_schedules', ['status'], unique=False)
    op.create_index(op.f('ix_charging_schedules_vehicle_id'), 'charging_schedules', ['vehicle_id'], unique=False)
    op.create_index('ix_schedule_charger_window', 'charging_schedules', ['charger_id', 'start_at', 'end_at'], unique=False)
    op.create_table('alerts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('type', sa.Enum('below_required_soc', 'session_interrupted', 'charger_fault', 'missed_slot', 'reservation_conflict', 'unexpected_consumption', 'peak_approaching', 'readiness_below_threshold', 'departed_below_required', 'manual_exception', name='ck_alerttype', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('severity', sa.Enum('critical', 'warning', 'info', name='ck_alertseverity', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('open', 'acknowledged', 'resolved', name='ck_alertstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('vehicle_id', sa.Integer(), nullable=True),
    sa.Column('charger_id', sa.Integer(), nullable=True),
    sa.Column('station_id', sa.Integer(), nullable=True),
    sa.Column('trip_id', sa.Integer(), nullable=True),
    sa.Column('schedule_id', sa.Integer(), nullable=True),
    sa.Column('dedup_key', sa.String(length=160), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acknowledged_by_id', sa.Integer(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by_id', sa.Integer(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['acknowledged_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['charger_id'], ['chargers.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['schedule_id'], ['charging_schedules.id'], ),
    sa.ForeignKeyConstraint(['station_id'], ['stations.id'], ),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_alerts_created_at'), 'alerts', ['created_at'], unique=False)
    op.create_index(op.f('ix_alerts_status'), 'alerts', ['status'], unique=False)
    op.create_index(op.f('ix_alerts_type'), 'alerts', ['type'], unique=False)
    op.create_index(op.f('ix_alerts_vehicle_id'), 'alerts', ['vehicle_id'], unique=False)
    op.create_index('uq_alert_open_dedup', 'alerts', ['dedup_key'], unique=True, postgresql_where=sa.text("dedup_key IS NOT NULL AND status <> 'resolved'"))
    op.create_table('charging_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('schedule_id', sa.Integer(), nullable=True),
    sa.Column('vehicle_id', sa.Integer(), nullable=False),
    sa.Column('charger_id', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('start_soc', sa.Float(), nullable=False),
    sa.Column('end_soc', sa.Float(), nullable=True),
    sa.Column('target_soc', sa.Float(), nullable=False),
    sa.Column('power_kw', sa.Float(), nullable=False),
    sa.Column('energy_kwh', sa.Float(), nullable=False),
    sa.Column('cost', sa.Float(), nullable=False),
    sa.Column('tariff_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Enum('active', 'completed', 'stopped', 'interrupted', name='ck_sessionstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('stop_reason', sa.String(length=160), nullable=True),
    sa.Column('source', sa.Enum('simulated', 'ocpp', 'manual', name='ck_sessionsource', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('ocpp_transaction_id', sa.Integer(), nullable=True),
    sa.Column('meter_start_wh', sa.Float(), nullable=True),
    sa.Column('last_reading_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['charger_id'], ['chargers.id'], ),
    sa.ForeignKeyConstraint(['schedule_id'], ['charging_schedules.id'], ),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ocpp_transaction_id')
    )
    op.create_index(op.f('ix_charging_sessions_charger_id'), 'charging_sessions', ['charger_id'], unique=False)
    op.create_index(op.f('ix_charging_sessions_schedule_id'), 'charging_sessions', ['schedule_id'], unique=False)
    op.create_index(op.f('ix_charging_sessions_started_at'), 'charging_sessions', ['started_at'], unique=False)
    op.create_index(op.f('ix_charging_sessions_status'), 'charging_sessions', ['status'], unique=False)
    op.create_index(op.f('ix_charging_sessions_vehicle_id'), 'charging_sessions', ['vehicle_id'], unique=False)
    op.create_index('uq_active_session_per_charger', 'charging_sessions', ['charger_id'], unique=True, postgresql_where=sa.text("status = 'active'"))
    op.create_index('uq_active_session_per_vehicle', 'charging_sessions', ['vehicle_id'], unique=True, postgresql_where=sa.text("status = 'active'"))
    op.create_table('energy_readings',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('charger_id', sa.Integer(), nullable=False),
    sa.Column('vehicle_id', sa.Integer(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('power_kw', sa.Float(), nullable=False),
    sa.Column('energy_kwh', sa.Float(), nullable=False),
    sa.Column('soc', sa.Float(), nullable=True),
    sa.Column('source', sa.Enum('simulated', 'ocpp', 'manual', name='ck_sessionsource', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.ForeignKeyConstraint(['charger_id'], ['chargers.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['charging_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_energy_readings_recorded_at'), 'energy_readings', ['recorded_at'], unique=False)
    op.create_index(op.f('ix_energy_readings_session_id'), 'energy_readings', ['session_id'], unique=False)
    op.execute(
        """
        ALTER TABLE charging_schedules
        ADD CONSTRAINT ex_charger_no_overlap
        EXCLUDE USING gist (charger_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)
        WHERE (status IN ('planned', 'active'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE charging_schedules DROP CONSTRAINT IF EXISTS ex_charger_no_overlap")
    op.drop_index(op.f('ix_energy_readings_session_id'), table_name='energy_readings')
    op.drop_index(op.f('ix_energy_readings_recorded_at'), table_name='energy_readings')
    op.drop_table('energy_readings')
    op.drop_index('uq_active_session_per_vehicle', table_name='charging_sessions', postgresql_where=sa.text("status = 'active'"))
    op.drop_index('uq_active_session_per_charger', table_name='charging_sessions', postgresql_where=sa.text("status = 'active'"))
    op.drop_index(op.f('ix_charging_sessions_vehicle_id'), table_name='charging_sessions')
    op.drop_index(op.f('ix_charging_sessions_status'), table_name='charging_sessions')
    op.drop_index(op.f('ix_charging_sessions_started_at'), table_name='charging_sessions')
    op.drop_index(op.f('ix_charging_sessions_schedule_id'), table_name='charging_sessions')
    op.drop_index(op.f('ix_charging_sessions_charger_id'), table_name='charging_sessions')
    op.drop_table('charging_sessions')
    op.drop_index('uq_alert_open_dedup', table_name='alerts', postgresql_where=sa.text("dedup_key IS NOT NULL AND status <> 'resolved'"))
    op.drop_index(op.f('ix_alerts_vehicle_id'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_type'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_status'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_created_at'), table_name='alerts')
    op.drop_table('alerts')
    op.drop_index('ix_schedule_charger_window', table_name='charging_schedules')
    op.drop_index(op.f('ix_charging_schedules_vehicle_id'), table_name='charging_schedules')
    op.drop_index(op.f('ix_charging_schedules_status'), table_name='charging_schedules')
    op.drop_index(op.f('ix_charging_schedules_run_id'), table_name='charging_schedules')
    op.drop_table('charging_schedules')
    op.drop_index('uq_open_request_per_vehicle', table_name='charging_requests', postgresql_where=sa.text("status IN ('scheduled', 'at_risk', 'unscheduled')"))
    op.drop_index(op.f('ix_charging_requests_vehicle_id'), table_name='charging_requests')
    op.drop_index(op.f('ix_charging_requests_trip_id'), table_name='charging_requests')
    op.drop_index(op.f('ix_charging_requests_status'), table_name='charging_requests')
    op.drop_table('charging_requests')
    op.drop_index(op.f('ix_trips_vehicle_id'), table_name='trips')
    op.drop_index(op.f('ix_trips_status'), table_name='trips')
    op.drop_index(op.f('ix_trips_departure_at'), table_name='trips')
    op.drop_table('trips')
    op.drop_index(op.f('ix_chargers_station_id'), table_name='chargers')
    op.drop_table('chargers')
    op.drop_index(op.f('ix_vehicles_registration'), table_name='vehicles')
    op.drop_index(op.f('ix_vehicles_is_active'), table_name='vehicles')
    op.drop_index(op.f('ix_vehicles_availability'), table_name='vehicles')
    op.drop_table('vehicles')
    op.drop_table('system_config')
    op.drop_index(op.f('ix_schedule_runs_created_at'), table_name='schedule_runs')
    op.drop_table('schedule_runs')
    op.drop_table('drivers')
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_category'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_users_role_code'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_table('tariff_periods')
    op.drop_index(op.f('ix_price_signals_starts_at'), table_name='price_signals')
    op.drop_table('price_signals')
    op.drop_table('stations')
    op.drop_table('service_providers')
    op.drop_table('roles')
    op.drop_index(op.f('ix_readiness_snapshots_recorded_at'), table_name='readiness_snapshots')
    op.drop_table('readiness_snapshots')
    op.drop_table('battery_profiles')
