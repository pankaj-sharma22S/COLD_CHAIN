export type RiskStatus = "NORMAL" | "RISKY" | "ERROR";
export type SimulationStatus = "RUNNING" | "STOPPED" | "ERROR";

export interface RiskReason { type: string; value?: unknown; message: string; severity?: string; }
export interface Risk { status: RiskStatus; truck_id?: string; reasons: RiskReason[]; }

export interface UpcomingWaypoint {
  waypoint_id: string | number;
  location_name: string;
  latitude: number;
  longitude: number;
  distance_km: number;
  travel_time_minutes?: number | null;
  eta?: string | null;
  expected_arrival_datetime?: string | null;
  temperature?: number | null;
  humidity?: number | null;
  risk_status: RiskStatus;
  risk_severity?: string | null;
  risk_reason?: string | null;
}

export interface Truck {
  id?: number;
  truck_id: string;
  trip_id?: string;
  timestamp: string;
  latitude: number;
  longitude: number;
  speed_kmh?: number | null;
  inside_temperature?: number | null;
  outside_temperature?: number | null;
  humidity?: number | null;
  door_status?: string | null;
  refrigeration_status?: string | null;
  current_point_name?: string | null;
  next_point_name?: string | null;
  segment_index?: number | null;
  segment_progress?: number | null;
  total_distance_km?: number | null;
  route_id?: string | null;
  cargo_policy_id?: string | null;
  cargo_type?: string | null;
  policy_min_temp?: number | null;
  policy_max_temp?: number | null;
  policy_target_temp?: number | null;
  source_name?: string | null;
  destination_name?: string | null;
  next_station?: { name?: string; latitude: number; longitude: number } | null;
  eta?: string | null;
  eta_status?: string | null;
  remaining_distance_km?: number | null;
  upcoming_waypoints?: UpcomingWaypoint[];
  risk: Risk;
  trip_status?: string | null;
}

export interface FleetResponse { timestamp: string; active_truck_count: number; risky_truck_count: number; active_trucks: Truck[]; }
export interface Simulation { status: SimulationStatus; truck_id?: string | null; trip_id?: string | null; route_id?: string | null; started_at?: string | null; last_error?: string | null; }
export interface AlertEvent { id: number; created_at: string; last_observed_at?: string; resolved_at?: string | null; duration_seconds?: number; acknowledged: boolean; status?: string; source: string; type: string; truck_id?: string | null; trip_id?: string | null; message: string; action: string; severity?: string | null; current_value?: number | null; threshold_violated?: string | null; }
export interface CargoPolicy { id: string; cargo_type: string; min_temperature: number; max_temperature: number; target_temperature: number; warning_margin: number; door_open_allowed_seconds: number; stopped_allowed_seconds: number; data_loss_allowed_seconds: number; is_active: boolean; }
export interface Weather { status?: string; error_type?: string; message?: string; temperature_c?: number; humidity_percent?: number; precipitation_mm?: number; rain_mm?: number; wind_speed_kmh?: number; weather_code?: number; requested_time?: string; weather_time?: string; latitude?: number; longitude?: number; }
export interface Trip { trip_id: string; truck_id: string; route_id: string; cargo_policy_id?: string | null; cargo_type?: string | null; status: string; started_at?: string | null; completed_at?: string | null; created_at?: string | null; }
export interface RoutePoint { name?: string | null; latitude: number; longitude: number; }
export interface Route { route_id: string; source: RoutePoint; destination: RoutePoint; waypoints: RoutePoint[]; geometry?: RoutePoint[]; distance_km: number; estimated_duration_minutes: number; }
export interface Telemetry extends Omit<Truck, "risk"> { }
export interface TripReport { report_type: string; truck_id: string; trip_id?: string; record_count: number; analysis_complete: boolean; safety_analysis?: { overall_status?: string; explanation?: string }; temperature_excursions?: Array<Record<string, unknown>>; door_events?: Array<Record<string, unknown>>; refrigeration_events?: Array<Record<string, unknown>>; stoppage_events?: Array<Record<string, unknown>>; key_findings?: string[]; recommendations?: string[]; route_analysis?: Record<string, unknown>; eta_analysis?: Record<string, unknown>; weather_correlation?: Record<string, unknown>; }

export interface AgentEvidence {
  status?: string;
  data_freshness?: {
    is_live_trip?: boolean;
    latest_telemetry_timestamp?: string;
    age_seconds?: number;
    is_fresh?: boolean;
    freshness_status?: string;
  };
  calculated_metrics?: {
    total_distance_km?: number;
    trip_wide_average_speed_kmh?: number;
    driving_only_average_speed_kmh?: number;
    arithmetic_sensor_average_speed_kmh?: number;
    max_valid_speed_kmh?: number;
    stationary_seconds?: number;
  };
  stops?: {
    stop_count?: number;
    ongoing_stops?: number;
    stops?: Array<{
      status: string;
      start_time: string;
      end_time: string;
      duration_minutes: number;
      location?: { location_name?: string };
    }>;
  };
  temperature_analysis?: {
    min_permitted_c?: number;
    max_permitted_c?: number;
    min_observed_temperature_c?: number;
    max_observed_temperature_c?: number;
    excursion_count?: number;
    cold_chain_maintained?: boolean;
  };
  incidents?: Array<Record<string, unknown>>;
}

export interface AgentChatResponse {
  status: "SUCCESS" | "NEEDS_CLARIFICATION" | "ERROR";
  trip_id?: string;
  truck_id?: string;
  intent?: string;
  response: string;
  evidence?: AgentEvidence | null;
}

export interface ChatMessage {
  id: string;
  sender: "user" | "assistant";
  text: string;
  timestamp: string;
  evidence?: AgentEvidence | null;
}
