"""Single authoritative deterministic cold-chain risk evaluation."""

from datetime import datetime, timezone
from backend.truck_rules import get_truck_rules_for_trip, TruckRules


def evaluate_truck_risk(truck_data: dict, rules: TruckRules | None = None) -> dict:
    """
    Evaluate one truck using the database-backed rules supplied or resolved for that truck/trip.

    Args:
        truck_data: Latest telemetry/state for the truck.
        rules: TruckRules object containing policy limits. If None, resolved from database.

    Returns:
        Risk result with NORMAL or RISKY status and detailed reasons.
    """
    truck_id = truck_data.get("truck_id", "UNKNOWN")
    trip_id = truck_data.get("trip_id")

    if rules is None:
        rules = get_truck_rules_for_trip(truck_id, trip_id=trip_id)

    reasons = []

    # ---------------------------------------------------------
    # 1. Temperature Excursion
    # ---------------------------------------------------------
    temperature = truck_data.get("inside_temperature")

    if temperature is not None:
        if temperature < rules.min_temperature:
            reasons.append({
                "type": "TEMPERATURE_LOW",
                "severity": "CRITICAL" if (rules.min_temperature - temperature) > 2.0 else "HIGH",
                "value": temperature,
                "safe_range": [
                    rules.min_temperature,
                    rules.max_temperature,
                ],
                "message": (
                    f"Temperature {temperature:.1f}°C is below "
                    f"the safe policy minimum of {rules.min_temperature:.1f}°C "
                    f"({rules.cargo_type})."
                ),
            })
        elif temperature > rules.max_temperature:
            reasons.append({
                "type": "TEMPERATURE_HIGH",
                "severity": "CRITICAL" if (temperature - rules.max_temperature) > 2.0 else "HIGH",
                "value": temperature,
                "safe_range": [
                    rules.min_temperature,
                    rules.max_temperature,
                ],
                "message": (
                    f"Temperature {temperature:.1f}°C is above "
                    f"the safe policy maximum of {rules.max_temperature:.1f}°C "
                    f"({rules.cargo_type})."
                ),
            })
        elif (rules.max_temperature - temperature) < rules.warning_margin or (temperature - rules.min_temperature) < rules.warning_margin:
            # Near boundary warning (non-critical, marked as warning)
            pass

    # ---------------------------------------------------------
    # 2. Door status & duration
    # ---------------------------------------------------------
    door_status = truck_data.get("door_status")
    door_open_duration = truck_data.get("door_open_duration_seconds", 0) or 0
    if door_status == "OPEN" and door_open_duration > rules.door_open_allowed_seconds:
        reasons.append({
            "type": "DOOR_OPEN",
            "severity": "HIGH",
            "value": door_status,
            "duration_seconds": door_open_duration,
            "allowed_duration_seconds": rules.door_open_allowed_seconds,
            "message": f"Truck door open for {int(door_open_duration)}s (exceeds allowed {rules.door_open_allowed_seconds}s limit).",
        })

    # ---------------------------------------------------------
    # 3. Refrigeration status
    # ---------------------------------------------------------
    refrigeration_status = truck_data.get("refrigeration_status")
    if refrigeration_status == "OFF":
        reasons.append({
            "type": "REFRIGERATION_OFF",
            "severity": "CRITICAL",
            "value": refrigeration_status,
            "message": "Refrigeration system is OFF.",
        })

    # ---------------------------------------------------------
    # 4. Vehicle stoppage
    # ---------------------------------------------------------
    speed = truck_data.get("speed_kmh")
    stopped_duration = truck_data.get("stopped_duration_seconds", 0) or 0
    if (
        speed is not None
        and speed <= 0
        and stopped_duration > rules.stopped_allowed_seconds
    ):
        reasons.append({
            "type": "TRUCK_STOPPED",
            "severity": "MEDIUM",
            "value": speed,
            "duration_seconds": stopped_duration,
            "allowed_duration_seconds": rules.stopped_allowed_seconds,
            "message": f"Truck has been stationary for {int(stopped_duration)}s (exceeds {rules.stopped_allowed_seconds}s limit).",
        })

    # ---------------------------------------------------------
    # 5. Telemetry Staleness (Timezone Normalized)
    # ---------------------------------------------------------
    raw_timestamp = truck_data.get("timestamp")
    if raw_timestamp is not None:
        now_dt = datetime.now(timezone.utc)
        if isinstance(raw_timestamp, str):
            try:
                # Handle ISO strings with Z or offsets
                clean_ts = raw_timestamp.replace("Z", "+00:00")
                parsed_dt = datetime.fromisoformat(clean_ts)
                if parsed_dt.tzinfo is None:
                    # Naive timestamp from local MySQL or UTC: calculate diff using naive local now
                    age_seconds = abs((datetime.now() - parsed_dt).total_seconds())
                else:
                    age_seconds = (now_dt - parsed_dt).total_seconds()
            except Exception:
                age_seconds = 0
        elif isinstance(raw_timestamp, datetime):
            if raw_timestamp.tzinfo is None:
                age_seconds = abs((datetime.now() - raw_timestamp).total_seconds())
            else:
                age_seconds = (now_dt - raw_timestamp).total_seconds()
        else:
            age_seconds = 0

        if age_seconds > rules.data_loss_allowed_seconds:
            reasons.append({
                "type": "TELEMETRY_STALE",
                "severity": "MEDIUM",
                "value": age_seconds,
                "allowed_duration_seconds": rules.data_loss_allowed_seconds,
                "message": f"Telemetry is stale ({int(age_seconds)}s old, exceeds {rules.data_loss_allowed_seconds}s freshness limit).",
            })

    # ---------------------------------------------------------
    # Final status
    # ---------------------------------------------------------
    status = "RISKY" if reasons else "NORMAL"

    return {
        "truck_id": rules.truck_id,
        "trip_id": trip_id,
        "cargo_policy_id": rules.cargo_policy_id,
        "cargo_type": rules.cargo_type,
        "status": status,
        "reasons": reasons,
    }


def evaluate_fleet_risk(active_trucks: list[dict]) -> dict:
    """
    Evaluate every active truck using its database-backed policy rules.
    """
    results = []

    for truck in active_trucks:
        truck_id = truck.get("truck_id", "UNKNOWN")
        trip_id = truck.get("trip_id")
        rules = get_truck_rules_for_trip(truck_id, trip_id=trip_id)

        result = evaluate_truck_risk(
            truck_data=truck,
            rules=rules,
        )
        results.append(result)

    risky_count = sum(1 for result in results if result["status"] == "RISKY")

    return {
        "truck_count": len(results),
        "risky_truck_count": risky_count,
        "normal_truck_count": len(results) - risky_count,
        "trucks": results,
    }


def evaluate_waypoint_risk(
    truck_data: dict,
    rules: TruckRules,
    waypoint_weather: dict | None,
    travel_time_minutes: float = 0.0,
) -> dict:
    """
    Deterministically evaluate risk for an upcoming waypoint along the route
    considering current cargo temperature, refrigeration state, door status,
    and forecasted ambient weather.
    """
    current_inside_temp = truck_data.get("inside_temperature")
    refrig_status = truck_data.get("refrigeration_status", "ON")
    door_status = truck_data.get("door_status", "CLOSED")

    outside_temp = waypoint_weather.get("temperature_c") if waypoint_weather else None

    reasons = []
    severity = "NORMAL"

    if current_inside_temp is not None:
        if current_inside_temp > rules.max_temperature:
            reasons.append(
                f"Cargo temp ({current_inside_temp:.1f}°C) exceeds safe limit ({rules.max_temperature:.1f}°C)"
            )
            severity = "HIGH"
        elif current_inside_temp < rules.min_temperature:
            reasons.append(
                f"Cargo temp ({current_inside_temp:.1f}°C) is below safe minimum ({rules.min_temperature:.1f}°C)"
            )
            severity = "HIGH"

    if refrig_status == "OFF":
        if outside_temp is not None and outside_temp > rules.max_temperature:
            reasons.append(
                f"Refrigeration OFF with {outside_temp:.1f}°C ambient exposes cargo beyond {rules.max_temperature:.1f}°C limit"
            )
            severity = "CRITICAL" if travel_time_minutes > 15 else "HIGH"
        else:
            reasons.append("Refrigeration system is OFF")
            if severity == "NORMAL":
                severity = "HIGH"

    if door_status == "OPEN":
        reasons.append("Door is open during transit, threatening cargo temperature integrity")
        if severity in ("NORMAL", "LOW"):
            severity = "MEDIUM"

    if outside_temp is not None and outside_temp >= 38.0 and refrig_status != "OFF":
        reasons.append(f"High ambient temperature ({outside_temp:.1f}°C) elevates thermal stress")
        if severity == "NORMAL":
            severity = "LOW"

    status = "RISKY" if reasons else "NORMAL"
    reason_str = "; ".join(reasons) if reasons else "Operating within safe limits"

    return {
        "status": status,
        "severity": severity,
        "reason": reason_str,
    }
