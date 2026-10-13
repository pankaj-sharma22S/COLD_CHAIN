"""Alert and incident management bridging database persistence with in-memory notification."""

from datetime import datetime, timezone
from threading import RLock
from typing import Any

from database.incident_repository import (
    upsert_incident,
    resolve_missing_incidents,
    acknowledge_incident as db_acknowledge_incident,
    list_incidents as db_list_incidents,
)

_lock = RLock()


def record_truck_incidents(truck: dict[str, Any]) -> None:
    """
    Authoritative ingestion-time risk assessment and persistent incident upsert.
    Called whenever telemetry is ingested.
    """
    truck_id = truck.get("truck_id")
    trip_id = truck.get("trip_id")
    if not truck_id or not trip_id:
        return

    risk = truck.get("risk") or {}
    status = risk.get("status")
    reasons = risk.get("reasons") or []

    active_risk_types = set()

    if status == "RISKY":
        for reason in reasons:
            risk_type = reason.get("type", "UNKNOWN_RISK")
            active_risk_types.add(risk_type)
            severity = reason.get("severity", "HIGH")
            message = reason.get("message", "Risk detected")
            val = reason.get("value")
            current_value = float(val) if isinstance(val, (int, float)) else None
            safe_range = reason.get("safe_range")
            threshold = str(safe_range) if safe_range else str(reason.get("allowed_duration_seconds", ""))

            upsert_incident(
                trip_id=trip_id,
                truck_id=truck_id,
                risk_type=risk_type,
                severity=severity,
                message=message,
                current_value=current_value,
                threshold_violated=threshold,
            )

    # Automatically resolve any previously ACTIVE incidents whose risk condition has cleared
    resolve_missing_incidents(
        trip_id=trip_id,
        truck_id=truck_id,
        active_risk_types=active_risk_types,
    )


def record_agent_action(action: Any) -> None:
    data = action.model_dump() if hasattr(action, "model_dump") else action
    if not isinstance(data, dict):
        return
    if data.get("action") not in {"ALERT", "NOTIFY_OPERATOR"}:
        return

    truck_id = data.get("truck_id") or "FLEET"
    trip_id = data.get("trip_id") or "MANUAL"
    severity = data.get("severity") or "MEDIUM"
    message = data.get("reason", "Agent action requires operator attention.")

    upsert_incident(
        trip_id=trip_id,
        truck_id=truck_id,
        risk_type="AGENT_ACTION",
        severity=severity,
        message=message,
        current_value=None,
        threshold_violated=data.get("action"),
    )


def list_events(
    trip_id: str | None = None,
    trip_ids: list[str] | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Fetch active and recent incidents from database with computed duration.
    For ACTIVE incidents, duration is elapsed time from detection to now.
    For RESOLVED incidents, duration is excursion time from detection to resolution.
    """
    incidents = db_list_incidents(status=status, trip_id=trip_id, trip_ids=trip_ids, limit=limit)
    now = datetime.now(timezone.utc)
    results = []

    for inc in incidents:
        first_det = inc.get("first_detected_at")
        last_obs = inc.get("last_observed_at")
        res_at = inc.get("resolved_at")

        # Compute duration
        duration_seconds = 0
        if first_det:
            # End time for duration calculation
            end_t = res_at if (inc.get("status") == "RESOLVED" and res_at) else now
            if hasattr(first_det, "tzinfo") and first_det.tzinfo is not None:
                if not (hasattr(end_t, "tzinfo") and end_t.tzinfo is not None):
                    end_t = end_t.replace(tzinfo=timezone.utc)
                duration_seconds = max(0, int((end_t - first_det).total_seconds()))
            else:
                det_naive = first_det
                end_naive = end_t.replace(tzinfo=None) if hasattr(end_t, "tzinfo") and end_t.tzinfo else end_t
                duration_seconds = max(0, int((end_naive - det_naive).total_seconds()))

        results.append({
            "id": inc["id"],
            "created_at": first_det.isoformat() if hasattr(first_det, "isoformat") else str(first_det),
            "last_observed_at": last_obs.isoformat() if hasattr(last_obs, "isoformat") else str(last_obs),
            "resolved_at": res_at.isoformat() if (res_at and hasattr(res_at, "isoformat")) else (str(res_at) if res_at else None),
            "duration_seconds": duration_seconds,
            "acknowledged": inc["status"] in ("ACKNOWLEDGED", "RESOLVED"),
            "status": inc["status"],
            "source": "RISK_ENGINE" if inc["risk_type"] != "AGENT_ACTION" else "LANGGRAPH",
            "type": inc["risk_type"],
            "truck_id": inc["truck_id"],
            "trip_id": inc["trip_id"],
            "message": inc["message"],
            "action": "ALERT",
            "severity": inc["severity"],
            "current_value": inc["current_value"],
            "threshold_violated": inc["threshold_violated"],
        })

    return results


def acknowledge_event(event_id: int) -> dict[str, Any] | None:
    inc = db_acknowledge_incident(event_id)
    if inc:
        return {
            "id": inc["id"],
            "status": inc["status"],
            "acknowledged": True,
            "acknowledged_at": inc["acknowledged_at"].isoformat() if inc.get("acknowledged_at") else None,
        }
    return None
