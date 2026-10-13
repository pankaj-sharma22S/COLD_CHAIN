"""Comprehensive evidence builder and data retrieval for the Cold Chain Operations Assistant."""

from datetime import datetime, timezone
from typing import Any

from database.connection import get_connection
from database.trip_repository import get_trip, list_trips
from database.policy_repository import get_policy_for_trip, get_policy
from database.route_repository import get_route
from database.incident_repository import list_incidents
from agent.operations_metrics import (
    calculate_speed_and_distance_metrics,
    detect_stops_and_timeline,
    analyze_temperature_excursions,
    analyze_door_and_refrigeration_events,
    parse_timestamp_utc,
)


def fetch_all_trip_telemetry(trip_id: str, max_records: int = 5000) -> list[dict[str, Any]]:
    """Fetch complete telemetry for a trip sorted chronologically without pagination omission."""
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT * FROM telemetry
               WHERE trip_id = %s
               ORDER BY timestamp ASC
               LIMIT %s""",
            (trip_id, max_records),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        connection.close()


def fetch_truck_latest_telemetry(truck_id: str) -> dict[str, Any] | None:
    """Fetch the single latest telemetry sample for a truck."""
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT * FROM telemetry
               WHERE truck_id = %s
               ORDER BY timestamp DESC
               LIMIT 1""",
            (truck_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()


def find_previous_trip(truck_id: str, current_trip_id: str) -> dict[str, Any] | None:
    """Retrieve the trip completed immediately prior to current_trip_id for the same truck."""
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        curr = get_trip(current_trip_id)
        curr_started = curr.get("started_at") if curr else None

        if curr_started:
            cursor.execute(
                """SELECT * FROM trips
                   WHERE truck_id = %s AND trip_id != %s AND started_at < %s
                   ORDER BY started_at DESC LIMIT 1""",
                (truck_id, current_trip_id, curr_started),
            )
        else:
            cursor.execute(
                """SELECT * FROM trips
                   WHERE truck_id = %s AND trip_id != %s
                   ORDER BY COALESCE(started_at, created_at) DESC LIMIT 1""",
                (truck_id, current_trip_id),
            )
        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()


def build_trip_evidence_package(
    trip_id: str,
    user_question: str,
    intent: str = "GENERAL_QUERY",
    include_comparison: bool = False,
) -> dict[str, Any]:
    """
    Build a structured, validated evidence object for the LLM.
    Fetches trip metadata, full telemetry, route, policy, stops, metrics, and incidents.
    """
    trip = get_trip(trip_id)
    if not trip:
        return {
            "error": "TRIP_NOT_FOUND",
            "trip_id": trip_id,
            "message": f"Trip '{trip_id}' was not found in the database.",
        }

    truck_id = trip["truck_id"]
    route_id = trip["route_id"]
    status = trip.get("status", "UNKNOWN")

    # 1. Full Telemetry History
    telemetry_records = fetch_all_trip_telemetry(trip_id)
    total_records = len(telemetry_records)

    # 2. Cargo Policy
    policy = get_policy_for_trip(trip_id)
    if not policy:
        pol_id = trip.get("cargo_policy_id") or "PHARMA_VACCINE"
        policy = get_policy(pol_id) or {
            "id": pol_id,
            "cargo_type": "Pharmaceutical Vaccines & Biologics",
            "min_temperature": 2.0,
            "max_temperature": 8.0,
            "target_temperature": 5.0,
        }

    # 3. Route Information
    route_obj = get_route(route_id) if route_id else None
    route_info = {
        "route_id": route_id,
        "source": route_obj.source.name if route_obj else None,
        "destination": route_obj.destination.name if route_obj else None,
        "distance_km": route_obj.distance_km if route_obj else None,
        "waypoints": [wp.name for wp in route_obj.waypoints] if route_obj else [],
    }

    # 4. Latest Telemetry & Freshness
    latest_sample = telemetry_records[-1] if telemetry_records else fetch_truck_latest_telemetry(truck_id)
    latest_ts = parse_timestamp_utc(latest_sample.get("timestamp")) if latest_sample else None
    now_utc = datetime.now(timezone.utc)

    if latest_ts:
        freshness_seconds = max(0, int((now_utc - latest_ts).total_seconds()))
        is_fresh = freshness_seconds <= 120
    else:
        freshness_seconds = None
        is_fresh = False

    data_freshness = {
        "is_live_trip": status == "ACTIVE",
        "latest_telemetry_timestamp": latest_ts.isoformat() if latest_ts else None,
        "age_seconds": freshness_seconds,
        "is_fresh": is_fresh,
        "freshness_status": "FRESH" if is_fresh else ("STALE" if status == "ACTIVE" else "COMPLETED_HISTORICAL"),
    }

    # 5. Deterministic Calculations
    motion_metrics = calculate_speed_and_distance_metrics(telemetry_records)
    stop_data = detect_stops_and_timeline(telemetry_records)
    temp_analysis = analyze_temperature_excursions(telemetry_records, policy)
    door_reefer_analysis = analyze_door_and_refrigeration_events(telemetry_records)

    # 6. Incidents
    incidents = list_incidents(trip_id=trip_id, limit=50)
    for inc in incidents:
        # Convert timestamp objects to strings for serialization
        for k in ["first_detected_at", "last_observed_at", "acknowledged_at", "resolved_at"]:
            if inc.get(k) and hasattr(inc[k], "isoformat"):
                inc[k] = inc[k].isoformat()

    # 7. Comparison Trip (if requested)
    comparison_evidence = None
    if include_comparison:
        prev_trip = find_previous_trip(truck_id, trip_id)
        if prev_trip:
            prev_telem = fetch_all_trip_telemetry(prev_trip["trip_id"], max_records=2000)
            prev_motion = calculate_speed_and_distance_metrics(prev_telem)
            prev_stops = detect_stops_and_timeline(prev_telem)
            prev_temp = analyze_temperature_excursions(prev_telem, policy)
            comparison_evidence = {
                "previous_trip_id": prev_trip["trip_id"],
                "status": prev_trip.get("status"),
                "started_at": str(prev_trip.get("started_at")),
                "completed_at": str(prev_trip.get("completed_at")),
                "record_count": len(prev_telem),
                "metrics": prev_motion,
                "stop_count": prev_stops["stop_count"],
                "excursion_count": prev_temp["excursion_count"],
            }

    # 8. Data Coverage
    first_sample_ts = parse_timestamp_utc(telemetry_records[0].get("timestamp")) if telemetry_records else None
    data_coverage = {
        "start_time": first_sample_ts.isoformat() if first_sample_ts else None,
        "end_time": latest_ts.isoformat() if latest_ts else None,
        "total_records_processed": total_records,
        "missing_sources": [] if telemetry_records else ["telemetry_empty"],
    }

    # 9. Lossless Event Timeline / Sample Repr
    # If telemetry is under 150 points, provide complete points. If larger, provide bounded sample head/tail + key events.
    if total_records <= 150:
        telemetry_sample = [
            {
                "timestamp": str(r.get("timestamp")),
                "speed_kmh": r.get("speed_kmh"),
                "inside_temp": r.get("inside_temperature"),
                "outside_temp": r.get("outside_temperature"),
                "door": r.get("door_status"),
                "refrigeration": r.get("refrigeration_status"),
                "location": r.get("current_point_name"),
            }
            for r in telemetry_records
        ]
    else:
        # First 20, last 20, plus all points during excursions or stops
        telemetry_sample = [
            {
                "timestamp": str(r.get("timestamp")),
                "speed_kmh": r.get("speed_kmh"),
                "inside_temp": r.get("inside_temperature"),
                "outside_temp": r.get("outside_temperature"),
                "door": r.get("door_status"),
                "refrigeration": r.get("refrigeration_status"),
                "location": r.get("current_point_name"),
            }
            for r in (telemetry_records[:20] + telemetry_records[-20:])
        ]

    package = {
        "trip_id": trip_id,
        "truck_id": truck_id,
        "status": status,
        "user_question": user_question,
        "resolved_intent": intent,
        "data_freshness": data_freshness,
        "data_coverage": data_coverage,
        "route": route_info,
        "cargo_policy": {
            "policy_id": policy.get("id"),
            "cargo_type": policy.get("cargo_type"),
            "min_temperature": policy.get("min_temperature"),
            "max_temperature": policy.get("max_temperature"),
            "target_temperature": policy.get("target_temperature"),
        },
        "calculated_metrics": motion_metrics,
        "stops": stop_data,
        "temperature_analysis": temp_analysis,
        "operational_events": door_reefer_analysis,
        "incidents": incidents,
        "telemetry_sample": telemetry_sample,
        "comparison_trip": comparison_evidence,
    }

    return package
