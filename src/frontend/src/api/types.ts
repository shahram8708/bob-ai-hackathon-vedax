export type Role = "admin" | "fleet_manager" | "operations_manager" | "charging_operator" | "driver" | "viewer";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  role_name: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  permissions: string[];
  driver_id: number | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Station {
  id: number;
  code: string;
  name: string;
  address: string;
  latitude: number;
  longitude: number;
  max_load_kw: number | null;
  solar_capacity_kw: number;
  battery_capacity_kwh: number;
  battery_power_kw: number;
  is_active: boolean;
}

export interface BatteryProfile {
  id: number;
  name: string;
  vehicle_type: string;
  capacity_kwh: number;
  max_ac_kw: number;
  max_dc_kw: number;
  charging_efficiency: number;
  consumption_kwh_per_km: number;
  connector_types: string[];
}

export interface TripBrief {
  id: number;
  code: string;
  destination: string;
  departure_at: string;
  return_at: string | null;
  required_soc: number | null;
  energy_kwh: number | null;
  distance_km: number;
  priority: string;
  status: string;
}

export interface ChargingRequest {
  id: number;
  vehicle_id: number;
  trip_id: number | null;
  status: string;
  priority_level: number;
  flexible: boolean;
  current_soc: number;
  target_soc: number;
  required_soc: number | null;
  energy_needed_kwh: number;
  deadline_at: string | null;
  projected_soc: number | null;
  shortfall_kwh: number;
  rules: string[];
  explanation: string;
  updated_at: string;
  vehicle?: string;
  trip_code?: string | null;
  departure_at?: string | null;
}

export type Readiness = "ready" | "charging" | "needs_charge" | "at_risk" | "on_trip" | "maintenance" | "out_of_service";

export interface Vehicle {
  id: number;
  registration: string;
  vehicle_type: string;
  battery_profile_id: number;
  battery_profile: string;
  connector_types: string[];
  battery_capacity_kwh: number;
  current_soc: number;
  min_operating_soc: number;
  required_departure_soc: number;
  max_soc: number;
  required_soc: number;
  home_station_id: number;
  current_station_id: number | null;
  latitude: number | null;
  longitude: number | null;
  availability: string;
  priority_category: string;
  assigned_driver_id: number | null;
  assigned_driver: string | null;
  is_active: boolean;
  soc_updated_at: string | null;
  charging_hold_until: string | null;
  notes: string;
  external_ref: string | null;
  next_trip: TripBrief | null;
  departure_at: string | null;
  trip_energy_kwh: number | null;
  energy_to_requirement_kwh: number;
  last_session: { id: number; started_at: string; ended_at: string | null; energy_kwh: number; end_soc: number | null; status: string } | null;
  request: ChargingRequest | null;
  readiness: Readiness;
}

export interface VehicleDetail extends Vehicle {
  trips: Trip[];
  reservations: Reservation[];
  sessions: { id: number; charger_id: number; started_at: string; ended_at: string | null; start_soc: number; end_soc: number | null; energy_kwh: number; cost: number; status: string; source: string }[];
  home_station: string;
  current_station: string | null;
}

export interface Trip extends TripBrief {
  vehicle_id: number | null;
  vehicle: string | null;
  driver_id: number | null;
  driver: string | null;
  origin_station_id: number;
  origin_station: string | null;
  destination_latitude: number | null;
  destination_longitude: number | null;
  departed_at: string | null;
  departure_soc: number | null;
  requirement_met: boolean | null;
  arrived_at: string | null;
  arrival_soc: number | null;
  actual_energy_kwh: number | null;
  external_ref: string | null;
  created_at: string;
}

export interface Driver {
  id: number;
  full_name: string;
  phone: string;
  license_number: string;
  home_station_id: number | null;
  user_id: number | null;
  user_email: string | null;
  is_active: boolean;
  vehicle?: string | null;
}

export interface Charger {
  id: number;
  code: string;
  station_id: number;
  station: string | null;
  connector_type: string;
  max_power_kw: number;
  power_limit_kw: number | null;
  effective_power_kw: number;
  status: string;
  status_note: string;
  status_changed_at: string | null;
  current_vehicle_id: number | null;
  current_vehicle: string | null;
  availability_schedule: { days: number[]; start: string; end: string }[] | null;
  bidirectional: boolean;
  ocpp_identity: string | null;
  ocpp_connected: boolean;
  last_heartbeat_at: string | null;
  is_active: boolean;
}

export interface TariffPeriod {
  id: number;
  name: string;
  kind: "peak" | "shoulder" | "off_peak" | "custom";
  start_time: string;
  end_time: string;
  rate_per_kwh: number;
  demand_charge_per_kw: number | null;
  days_of_week: number[];
  station_id: number | null;
  is_active: boolean;
}

export interface TariffSlot {
  at: string;
  kind: string;
  rate: number;
  name: string;
  source: string;
}

export interface Reservation {
  id: number;
  run_id: number | null;
  request_id: number | null;
  vehicle_id: number;
  vehicle: string | null;
  charger_id: number;
  charger: string | null;
  station_id: number | null;
  start_at: string;
  end_at: string;
  power_kw: number;
  planned_energy_kwh: number;
  estimated_cost: number;
  target_soc: number;
  priority_level: number;
  status: string;
  is_override: boolean;
  override_reason: string | null;
  rules: string[];
  explanation: string;
  tariff_mix: Record<string, number>;
  created_at?: string;
}

export interface ScheduleRun {
  id: number;
  created_at: string;
  trigger: string;
  mode: string;
  status: string;
  duration_ms: number;
  vehicles_evaluated: number;
  vehicles_needing_charge: number;
  reservations_created: number;
  reservations_kept: number;
  reservations_superseded: number;
  conflicts_prevented: number;
  at_risk_count: number;
  planned_energy_kwh: number;
  planned_cost: number;
  approved_at: string | null;
  summary: Record<string, unknown>;
}

export interface Session {
  id: number;
  schedule_id: number | null;
  vehicle_id: number;
  vehicle: string | null;
  charger_id: number;
  charger: string | null;
  started_at: string;
  ended_at: string | null;
  start_soc: number;
  end_soc: number | null;
  current_soc: number | null;
  target_soc: number;
  power_kw: number;
  energy_kwh: number;
  cost: number;
  tariff_breakdown: Record<string, { kwh: number; cost: number }>;
  status: string;
  stop_reason: string | null;
  source: string;
  scheduled_end_at: string | null;
}

export interface Alert {
  id: number;
  type: string;
  severity: "critical" | "warning" | "info";
  status: "open" | "acknowledged" | "resolved";
  title: string;
  message: string;
  vehicle_id: number | null;
  vehicle: string | null;
  charger_id: number | null;
  charger: string | null;
  station_id: number | null;
  trip_id: number | null;
  schedule_id: number | null;
  details: Record<string, unknown>;
  created_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
}

export interface PlanMetrics {
  vehicles_evaluated: number;
  vehicles_needing_charge: number;
  scheduled: number;
  at_risk: number;
  unscheduled: number;
  satisfied: number;
  locked: number;
  away: number;
  reservations: number;
  planned_energy_kwh: number;
  planned_cost: number;
  avg_rate_per_kwh: number;
  shortfall_kwh: number;
  energy_by_period: Record<string, number>;
  peak_energy_kwh: number;
  peak_share_pct: number;
  off_peak_share_pct: number;
  departures_in_horizon: number;
  ready_now: number;
  projected_ready: number;
  projected_readiness_pct: number;
  missed_requirements: number;
  conflicts_prevented: number;
  peak_site_load_kw: number;
  demand_charge_estimate: number;
}

export interface Comparison {
  as_of: string;
  currency: string;
  baseline: PlanMetrics;
  rule_based: PlanMetrics;
  delta: Record<string, number | null>;
  lp_benchmark?: {
    status: string;
    lower_bound_cost: number | null;
    avg_rate_per_kwh?: number;
    energy_kwh: number | null;
    shortfall_kwh: number | null;
    peak_share_pct?: number;
    vehicles?: number;
    variables: number;
    solve_ms: number;
    rule_based_gap_pct?: number;
  };
}

export interface OperationalConfig {
  timezone: string;
  currency: string;
  scheduler_mode: "baseline" | "rule_based";
  slot_minutes: number;
  horizon_hours: number;
  departure_buffer_minutes: number;
  urgent_window_hours: number;
  flex_slack_minutes: number;
  tariff_optimization: boolean;
  emergency_override: boolean;
  tie_breakers: string[];
  required_soc_mode: "operator" | "rule";
  safety_reserve_type: "percent" | "kwh";
  safety_reserve_value: number;
  readiness_threshold_pct: number;
  readiness_window_hours: number;
  at_risk_warning_hours: number;
  missed_slot_grace_minutes: number;
  peak_warning_minutes: number;
  unexpected_consumption_pct: number;
  auto_recalc_minutes: number;
  require_schedule_approval: boolean;
  default_rate_per_kwh: number;
  simulation_enabled: boolean;
  clock_offset_seconds: number;
  v2g_enabled: boolean;
  v2g_soc_buffer: number;
  v2g_export_rate_per_kwh: number;
  v2g_min_dwell_hours: number;
  storage_round_trip_efficiency: number;
  webhook_url: string | null;
}

export interface ReportData {
  key: string;
  title: string;
  description: string;
  columns: { key: string; label: string }[];
  rows: Record<string, unknown>[];
  summary: Record<string, unknown>;
  series: Record<string, unknown>[];
  simulated: boolean;
}

export interface AuditEntry {
  id: number;
  created_at: string;
  actor: string;
  action: string;
  category: string;
  entity_type: string | null;
  entity_id: string | null;
  summary: string;
  details: Record<string, unknown>;
  ip_address: string | null;
}
