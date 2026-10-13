"""Enrich active trucks with route, ETA, and upcoming waypoint intelligence."""

from datetime import datetime, timezone

from database.route_repository import get_route
from backend.eta_service import ETAService
from retrieval.active_retrieval import get_active_trucks
from backend.truck_rules import get_truck_rules
from backend.risk_engine import evaluate_waypoint_risk
from weather.weather_service import WeatherService
from backend.geocoding import get_location_name


def get_active_trucks_with_eta() -> dict:
    """
    Get all active trucks and enrich them with:
    - route information
    - next station
    - remaining distance
    - ETA
    - upcoming_waypoints with location names, weather, and deterministic risk
    """
    active_data = get_active_trucks()
    eta_service = ETAService()

    enriched_trucks = []

    for truck in active_data["active_trucks"]:
        truck_id = truck["truck_id"]
        route_id = truck.get("route_id")

        trip_id = truck.get("trip_id")
        try:
            from backend.truck_rules import get_truck_rules_for_trip
            rules = get_truck_rules_for_trip(truck_id, trip_id=trip_id)
        except Exception:
            # Fallback nominal rules if unknown truck
            from backend.truck_rules import TruckRules
            rules = TruckRules(truck_id=truck_id, min_temperature=2.0, max_temperature=8.0)

        if not route_id:
            enriched_trucks.append({
                **truck,
                "next_station": None,
                "eta": None,
                "eta_status": "ROUTE_NOT_FOUND",
                "upcoming_waypoints": [],
            })
            continue

        route = get_route(route_id)

        if route is None:
            enriched_trucks.append({
                **truck,
                "next_station": None,
                "eta": None,
                "eta_status": "ROUTE_NOT_FOUND",
                "upcoming_waypoints": [],
            })
            continue

        current_time = truck["timestamp"]
        if isinstance(current_time, str):
            current_time = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        # 1. Overall destination ETA
        eta_result = eta_service.get_eta(
            route=route,
            current_lat=truck["latitude"],
            current_lon=truck["longitude"],
            current_speed_kmh=truck.get("speed_kmh"),
            current_time=current_time,
            segment_index=truck.get("segment_index"),
            segment_progress=truck.get("segment_progress"),
        )

        # 2. Upcoming waypoints along the route
        raw_waypoints_eta = eta_service.get_waypoints_eta(
            route=route,
            current_lat=truck["latitude"],
            current_lon=truck["longitude"],
            current_speed_kmh=truck.get("speed_kmh"),
            current_time=current_time,
            segment_index=truck.get("segment_index"),
            segment_progress=truck.get("segment_progress"),
        )


        upcoming_waypoints = []
        for wp in raw_waypoints_eta:
            # Human-readable location name
            loc_name = get_location_name(
                wp["latitude"],
                wp["longitude"],
                default_name=wp.get("location_name"),
            )

            # Weather at waypoint expected arrival datetime
            arrival_dt = datetime.fromisoformat(wp["expected_arrival_datetime"])
            wp_weather = WeatherService.get_weather(
                latitude=wp["latitude"],
                longitude=wp["longitude"],
                requested_time=arrival_dt,
            )

            # Deterministic waypoint risk
            wp_risk = evaluate_waypoint_risk(
                truck_data=truck,
                rules=rules,
                waypoint_weather=wp_weather,
                travel_time_minutes=wp["travel_time_minutes"],
            )

            upcoming_waypoints.append({
                "waypoint_id": wp["waypoint_id"],
                "location_name": loc_name,
                "latitude": wp["latitude"],
                "longitude": wp["longitude"],
                "distance_km": wp["distance_km"],
                "travel_time_minutes": wp["travel_time_minutes"],
                "eta": wp["eta"],
                "expected_arrival_datetime": wp["expected_arrival_datetime"],
                "temperature": wp_weather.get("temperature_c"),
                "humidity": wp_weather.get("humidity_percent"),
                "risk_status": wp_risk["status"],
                "risk_severity": wp_risk["severity"],
                "risk_reason": wp_risk["reason"],
            })

        # Next station is the first upcoming milestone
        next_station = None
        if upcoming_waypoints:
            next_station = {
                "name": upcoming_waypoints[0]["location_name"],
                "latitude": upcoming_waypoints[0]["latitude"],
                "longitude": upcoming_waypoints[0]["longitude"],
            }
        else:
            next_station = {
                "name": route.destination.name,
                "latitude": route.destination.latitude,
                "longitude": route.destination.longitude,
            }

        # Resolve current point name if missing or raw
        current_loc_name = truck.get("current_point_name")
        if not current_loc_name or current_loc_name.startswith("Point_"):
            current_loc_name = get_location_name(
                truck["latitude"],
                truck["longitude"],
                default_name=route.source.name,
            )

        destination_eta = eta_result.get("eta")
        if isinstance(destination_eta, datetime):
            destination_eta = destination_eta.isoformat()

        enriched_trucks.append({
            **truck,
            "current_point_name": current_loc_name,
            "next_point_name": next_station["name"] if next_station else None,
            "next_station": next_station,
            "eta": destination_eta,
            "eta_status": eta_result.get("status"),
            "remaining_distance_km": eta_result.get("remaining_distance_km"),
            "travel_time_minutes": eta_result.get("travel_time_minutes"),
            "upcoming_waypoints": upcoming_waypoints,
        })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_truck_count": len(enriched_trucks),
        "active_trucks": enriched_trucks,
    }


if __name__ == "__main__":
    result = get_active_trucks_with_eta()
    print(f"Enriched active trucks: {result['active_truck_count']}")
    for t in result["active_trucks"]:
        print(f"Truck {t['truck_id']}: next={t['next_point_name']}, waypoints={len(t['upcoming_waypoints'])}")
