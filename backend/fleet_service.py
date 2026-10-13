"""Read-only composition service for the dashboard fleet view."""

from datetime import datetime
from retrieval.eta_route_retrieval import get_active_trucks_with_eta
from backend.risk_engine import evaluate_fleet_risk
from weather.weather_service import WeatherService


def get_dashboard_fleet() -> dict:
    """
    Pure read-only endpoint returning current fleet status, ETAs, and policy risks.
    No mutation side-effects on polling.
    """
    eta_data = get_active_trucks_with_eta()
    risks = evaluate_fleet_risk(eta_data["active_trucks"])
    by_truck = {item["truck_id"]: item for item in risks["trucks"]}

    trucks = []
    for truck in eta_data["active_trucks"]:
        risk = by_truck.get(truck["truck_id"], {
            "status": "ERROR",
            "reasons": [{"type": "RISK_UNAVAILABLE", "message": "Risk unavailable."}],
        })
        trucks.append({**truck, "risk": risk})

    result = {
        "timestamp": eta_data["timestamp"],
        "active_truck_count": len(trucks),
        "risky_truck_count": sum(1 for truck in trucks if truck["risk"]["status"] == "RISKY"),
        "active_trucks": trucks,
    }
    return result


def get_truck_weather(truck_id: str) -> dict:
    for truck in get_active_trucks_with_eta()["active_trucks"]:
        if truck["truck_id"] != truck_id:
            continue
        station = truck.get("next_station")
        eta = truck.get("eta")
        if not station or not eta:
            return {"status": "UNAVAILABLE", "error_type": "ETA_OR_STATION_UNAVAILABLE"}
        if isinstance(eta, str):
            eta = datetime.fromisoformat(eta.replace("Z", "+00:00"))
        return WeatherService.get_weather(station["latitude"], station["longitude"], eta)
    return {"status": "UNAVAILABLE", "error_type": "TRUCK_NOT_ACTIVE"}
