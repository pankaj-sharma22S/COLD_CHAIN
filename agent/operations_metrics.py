"""Deterministic calculation and temporal event analysis for cold-chain operations."""

import math
from datetime import datetime, timezone
from typing import Any


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute Great Circle distance between two points in kilometers."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def parse_timestamp_utc(ts: Any) -> datetime | None:
    """Normalize any timestamp representation (ISO string, datetime) into UTC datetime."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    if isinstance(ts, str):
        try:
            clean = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None


def calculate_speed_and_distance_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Deterministically calculate:
    - total_distance_km (odometer/telemetry progression or GPS cumulative)
    - trip_wide_average_speed_kmh (total distance / total trip elapsed time including stops)
    - driving_only_average_speed_kmh (distance while moving / moving time)
    - arithmetic_sensor_average_speed_kmh (mean of valid speed sensor samples)
    - max_valid_speed_kmh and min_valid_speed_kmh
    - total_elapsed_seconds, driving_seconds, stationary_seconds
    """
    if not records:
        return {
            "total_distance_km": 0.0,
            "trip_wide_average_speed_kmh": 0.0,
            "driving_only_average_speed_kmh": 0.0,
            "arithmetic_sensor_average_speed_kmh": 0.0,
            "max_valid_speed_kmh": 0.0,
            "min_valid_speed_kmh": 0.0,
            "total_elapsed_seconds": 0.0,
            "driving_seconds": 0.0,
            "stationary_seconds": 0.0,
            "valid_speed_sample_count": 0,
        }

    valid_speeds = []
    first_time = parse_timestamp_utc(records[0].get("timestamp"))
    last_time = parse_timestamp_utc(records[-1].get("timestamp"))
    total_elapsed_seconds = (
        max(0.0, (last_time - first_time).total_seconds()) if (first_time and last_time) else 0.0
    )

    driving_seconds = 0.0
    stationary_seconds = 0.0
    moving_distance_km = 0.0

    # Sort records chronologically
    sorted_recs = sorted(
        records,
        key=lambda r: parse_timestamp_utc(r.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
    )

    for i in range(len(sorted_recs)):
        curr = sorted_recs[i]
        speed = curr.get("speed_kmh")
        if speed is not None and 0.0 <= speed <= 150.0:
            valid_speeds.append(float(speed))

        if i > 0:
            prev = sorted_recs[i - 1]
            t_prev = parse_timestamp_utc(prev.get("timestamp"))
            t_curr = parse_timestamp_utc(curr.get("timestamp"))
            if t_prev and t_curr and t_curr > t_prev:
                dt = (t_curr - t_prev).total_seconds()
                # Segment speed approximation
                curr_spd = speed if (speed is not None and speed >= 0) else 0.0
                if curr_spd > 1.0:
                    driving_seconds += dt
                    moving_distance_km += (curr_spd * dt) / 3600.0
                else:
                    stationary_seconds += dt

    # Distance calculation: prefer total_distance_km progression if reported by simulator/odometer
    last_td = sorted_recs[-1].get("total_distance_km")
    first_td = sorted_recs[0].get("total_distance_km")
    if last_td is not None and first_td is not None and last_td >= first_td:
        total_distance_km = round(float(last_td - first_td), 2)
    elif moving_distance_km > 0:
        total_distance_km = round(moving_distance_km, 2)
    else:
        # Fallback GPS cumulative distance
        gps_dist = 0.0
        for i in range(1, len(sorted_recs)):
            p1, p2 = sorted_recs[i - 1], sorted_recs[i]
            if (
                p1.get("latitude") is not None
                and p1.get("longitude") is not None
                and p2.get("latitude") is not None
                and p2.get("longitude") is not None
            ):
                d = haversine_distance_km(
                    p1["latitude"], p1["longitude"], p2["latitude"], p2["longitude"]
                )
                if d < 50.0:  # noise filter for teleportation
                    gps_dist += d
        total_distance_km = round(gps_dist, 2)

    total_hours = total_elapsed_seconds / 3600.0 if total_elapsed_seconds > 0 else 0.0
    driving_hours = driving_seconds / 3600.0 if driving_seconds > 0 else 0.0

    trip_wide_avg = round(total_distance_km / total_hours, 2) if total_hours > 0 else 0.0
    driving_only_avg = round(total_distance_km / driving_hours, 2) if driving_hours > 0 else 0.0
    sensor_avg = round(sum(valid_speeds) / len(valid_speeds), 2) if valid_speeds else 0.0
    max_spd = round(max(valid_speeds), 2) if valid_speeds else 0.0
    min_spd = round(min(valid_speeds), 2) if valid_speeds else 0.0

    return {
        "total_distance_km": total_distance_km,
        "trip_wide_average_speed_kmh": trip_wide_avg,
        "driving_only_average_speed_kmh": driving_only_avg,
        "arithmetic_sensor_average_speed_kmh": sensor_avg,
        "max_valid_speed_kmh": max_spd,
        "min_valid_speed_kmh": min_spd,
        "total_elapsed_seconds": round(total_elapsed_seconds, 1),
        "driving_seconds": round(driving_seconds, 1),
        "stationary_seconds": round(stationary_seconds, 1),
        "valid_speed_sample_count": len(valid_speeds),
    }


def detect_stops_and_timeline(
    records: list[dict[str, Any]],
    speed_threshold_kmh: float = 1.0,
    min_stop_duration_seconds: float = 40.0,
) -> dict[str, Any]:
    """
    Detect completed and ongoing stops.
    A stop is a continuous stationary interval (speed <= speed_threshold_kmh)
    lasting >= min_stop_duration_seconds.
    """
    if not records:
        return {"stop_count": 0, "ongoing_stops": 0, "stops": [], "total_stop_duration_seconds": 0.0}

    sorted_recs = sorted(
        records,
        key=lambda r: parse_timestamp_utc(r.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
    )

    stops = []
    current_stop_start = None
    current_stop_last = None
    current_stop_loc = None

    for r in sorted_recs:
        spd = r.get("speed_kmh")
        ts = parse_timestamp_utc(r.get("timestamp"))
        if ts is None:
            continue

        is_stopped = spd is not None and spd <= speed_threshold_kmh

        if is_stopped:
            if current_stop_start is None:
                current_stop_start = ts
                current_stop_loc = {
                    "latitude": r.get("latitude"),
                    "longitude": r.get("longitude"),
                    "location_name": r.get("current_point_name") or "In transit",
                }
            current_stop_last = ts
        else:
            if current_stop_start is not None and current_stop_last is not None:
                duration_sec = (current_stop_last - current_stop_start).total_seconds()
                if duration_sec >= min_stop_duration_seconds:
                    stops.append({
                        "status": "COMPLETED",
                        "start_time": current_stop_start.isoformat(),
                        "end_time": current_stop_last.isoformat(),
                        "duration_seconds": round(duration_sec, 1),
                        "duration_minutes": round(duration_sec / 60.0, 1),
                        "location": current_stop_loc,
                    })
                current_stop_start = None
                current_stop_last = None
                current_stop_loc = None

    ongoing_count = 0
    # Check if a stop was ongoing at the final sample
    if current_stop_start is not None and current_stop_last is not None:
        duration_sec = (current_stop_last - current_stop_start).total_seconds()
        if duration_sec >= min_stop_duration_seconds:
            stops.append({
                "status": "ONGOING",
                "start_time": current_stop_start.isoformat(),
                "end_time": current_stop_last.isoformat(),
                "duration_seconds": round(duration_sec, 1),
                "duration_minutes": round(duration_sec / 60.0, 1),
                "location": current_stop_loc,
            })
            ongoing_count = 1

    total_duration = sum(s["duration_seconds"] for s in stops)

    return {
        "stop_count": len([s for s in stops if s["status"] == "COMPLETED"]),
        "ongoing_stops": ongoing_count,
        "stops": stops,
        "total_stop_duration_seconds": round(total_duration, 1),
    }


def analyze_temperature_excursions(
    records: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """
    Deterministic temperature excursion analysis against cargo policy min/max limits.
    """
    min_limit = float(policy.get("min_temperature", 2.0))
    max_limit = float(policy.get("max_temperature", 8.0))
    target_temp = float(policy.get("target_temperature", 5.0))

    if not records:
        return {
            "policy_id": policy.get("id", "UNKNOWN"),
            "cargo_type": policy.get("cargo_type", "Standard"),
            "min_permitted_c": min_limit,
            "max_permitted_c": max_limit,
            "target_temperature_c": target_temp,
            "min_observed_temperature_c": None,
            "max_observed_temperature_c": None,
            "excursion_count": 0,
            "total_excursion_duration_seconds": 0.0,
            "excursions": [],
            "cold_chain_maintained": True,
        }

    sorted_recs = sorted(
        records,
        key=lambda r: parse_timestamp_utc(r.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
    )

    valid_temps = [
        float(r["inside_temperature"])
        for r in sorted_recs
        if r.get("inside_temperature") is not None
    ]
    min_obs = round(min(valid_temps), 2) if valid_temps else None
    max_obs = round(max(valid_temps), 2) if valid_temps else None

    excursions = []
    current_exc = None

    for r in sorted_recs:
        temp = r.get("inside_temperature")
        ts = parse_timestamp_utc(r.get("timestamp"))
        if temp is None or ts is None:
            continue

        temp = float(temp)
        direction = None
        if temp > max_limit:
            direction = "HIGH"
        elif temp < min_limit:
            direction = "LOW"

        if direction:
            if current_exc is None:
                current_exc = {
                    "direction": direction,
                    "start_time": ts,
                    "end_time": ts,
                    "min_temp": temp,
                    "max_temp": temp,
                    "temperatures": [temp],
                }
            else:
                if current_exc["direction"] == direction:
                    current_exc["end_time"] = ts
                    current_exc["min_temp"] = min(current_exc["min_temp"], temp)
                    current_exc["max_temp"] = max(current_exc["max_temp"], temp)
                    current_exc["temperatures"].append(temp)
                else:
                    # Direction flipped
                    dur = max(0.0, (current_exc["end_time"] - current_exc["start_time"]).total_seconds())
                    excursions.append({
                        "direction": current_exc["direction"],
                        "start_time": current_exc["start_time"].isoformat(),
                        "end_time": current_exc["end_time"].isoformat(),
                        "duration_seconds": round(dur, 1),
                        "duration_minutes": round(dur / 60.0, 1),
                        "peak_deviation": current_exc["max_temp"] if current_exc["direction"] == "HIGH" else current_exc["min_temp"],
                        "safe_range": [min_limit, max_limit],
                    })
                    current_exc = {
                        "direction": direction,
                        "start_time": ts,
                        "end_time": ts,
                        "min_temp": temp,
                        "max_temp": temp,
                        "temperatures": [temp],
                    }
        else:
            if current_exc is not None:
                dur = max(0.0, (current_exc["end_time"] - current_exc["start_time"]).total_seconds())
                excursions.append({
                    "direction": current_exc["direction"],
                    "start_time": current_exc["start_time"].isoformat(),
                    "end_time": current_exc["end_time"].isoformat(),
                    "duration_seconds": round(dur, 1),
                    "duration_minutes": round(dur / 60.0, 1),
                    "peak_deviation": current_exc["max_temp"] if current_exc["direction"] == "HIGH" else current_exc["min_temp"],
                    "safe_range": [min_limit, max_limit],
                })
                current_exc = None

    if current_exc is not None:
        dur = max(0.0, (current_exc["end_time"] - current_exc["start_time"]).total_seconds())
        excursions.append({
            "direction": current_exc["direction"],
            "start_time": current_exc["start_time"].isoformat(),
            "end_time": current_exc["end_time"].isoformat(),
            "duration_seconds": round(dur, 1),
            "duration_minutes": round(dur / 60.0, 1),
            "peak_deviation": current_exc["max_temp"] if current_exc["direction"] == "HIGH" else current_exc["min_temp"],
            "safe_range": [min_limit, max_limit],
        })

    total_exc_duration = sum(e["duration_seconds"] for e in excursions)

    return {
        "policy_id": policy.get("id", "PHARMA_VACCINE"),
        "cargo_type": policy.get("cargo_type", "Standard Cold Chain"),
        "min_permitted_c": min_limit,
        "max_permitted_c": max_limit,
        "target_temperature_c": target_temp,
        "min_observed_temperature_c": min_obs,
        "max_observed_temperature_c": max_obs,
        "excursion_count": len(excursions),
        "total_excursion_duration_seconds": round(total_exc_duration, 1),
        "excursions": excursions,
        "cold_chain_maintained": len(excursions) == 0,
    }


def analyze_door_and_refrigeration_events(records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Extract discrete door-open and refrigeration-OFF events with durations.
    """
    sorted_recs = sorted(
        records,
        key=lambda r: parse_timestamp_utc(r.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
    )

    door_events = []
    door_start = None
    door_last = None

    reefer_events = []
    reefer_start = None
    reefer_last = None

    for r in sorted_recs:
        ts = parse_timestamp_utc(r.get("timestamp"))
        if ts is None:
            continue

        # Door
        door = r.get("door_status")
        if door == "OPEN":
            if door_start is None:
                door_start = ts
            door_last = ts
        else:
            if door_start and door_last:
                d_sec = max(0.0, (door_last - door_start).total_seconds())
                door_events.append({
                    "start_time": door_start.isoformat(),
                    "end_time": door_last.isoformat(),
                    "duration_seconds": round(d_sec, 1),
                })
                door_start, door_last = None, None

        # Reefer
        reefer = r.get("refrigeration_status")
        if reefer == "OFF":
            if reefer_start is None:
                reefer_start = ts
            reefer_last = ts
        else:
            if reefer_start and reefer_last:
                r_sec = max(0.0, (reefer_last - reefer_start).total_seconds())
                reefer_events.append({
                    "start_time": reefer_start.isoformat(),
                    "end_time": reefer_last.isoformat(),
                    "duration_seconds": round(r_sec, 1),
                })
                reefer_start, reefer_last = None, None

    if door_start and door_last:
        door_events.append({
            "start_time": door_start.isoformat(),
            "end_time": door_last.isoformat(),
            "duration_seconds": round((door_last - door_start).total_seconds(), 1),
        })

    if reefer_start and reefer_last:
        reefer_events.append({
            "start_time": reefer_start.isoformat(),
            "end_time": reefer_last.isoformat(),
            "duration_seconds": round((reefer_last - reefer_start).total_seconds(), 1),
        })

    return {
        "door_events": door_events,
        "door_event_count": len(door_events),
        "refrigeration_off_events": reefer_events,
        "refrigeration_off_count": len(reefer_events),
    }
