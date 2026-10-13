"""Deterministic road-distance-based ETA calculation service."""

import logging
from datetime import datetime, timezone, timedelta
from backend.route import Route, MapPoint

logger = logging.getLogger("eta_service")
logging.basicConfig(level=logging.INFO)


class ETAService:

    @staticmethod
    def _get_road_projections(route: Route):
        """
        Calculate cumulative road distances along the route geometry.
        """
        pts = route.road_points
        cum_dists = [0.0] * len(pts)
        for i in range(1, len(pts)):
            cum_dists[i] = cum_dists[i - 1] + route.distance_between(pts[i - 1], pts[i])
        return pts, cum_dists

    @staticmethod
    def _compute_truck_road_distance(
        route: Route,
        pts: list[MapPoint],
        cum_dists: list[float],
        current_lat: float,
        current_lon: float,
        segment_index: int | None = None,
        segment_progress: float | None = None,
    ) -> float:
        """
        Determine the truck's cumulative road distance from origin.
        Prefers segment_index/progress if valid, otherwise projects coordinates.
        """
        if (
            segment_index is not None
            and 0 <= segment_index < len(pts) - 1
            and segment_progress is not None
            and 0.0 <= segment_progress <= 1.0
        ):
            seg_dist = route.distance_between(pts[segment_index], pts[segment_index + 1])
            return cum_dists[segment_index] + (seg_dist * segment_progress)

        current_point = MapPoint(latitude=current_lat, longitude=current_lon)
        min_dist = float("inf")
        closest_idx = 0
        for idx, pt in enumerate(pts):
            d = route.distance_between(pt, current_point)
            if d < min_dist:
                min_dist = d
                closest_idx = idx

        return cum_dists[closest_idx]

    @staticmethod
    def get_eta(
        route: Route,
        current_lat: float,
        current_lon: float,
        current_speed_kmh: float | None,
        current_time: datetime,
        segment_index: int | None = None,
        segment_progress: float | None = None,
    ) -> dict:
        """
        Calculate overall destination ETA from the truck's current state.
        Uses actual road geometry distance rather than straight-line approximations.
        """
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        current_time = current_time.astimezone(timezone.utc)

        pts, cum_dists = ETAService._get_road_projections(route)
        total_road_dist = cum_dists[-1]

        truck_road_dist = ETAService._compute_truck_road_distance(
            route, pts, cum_dists, current_lat, current_lon, segment_index, segment_progress
        )
        remaining_distance = max(0.0, total_road_dist - truck_road_dist)

        # Handle effective speed: if stopped, use nominal route speed (45.0 km/h)
        # to ensure operations still have an estimated arrival time
        is_stopped = current_speed_kmh is None or current_speed_kmh < 5.0
        effective_speed = 45.0 if is_stopped else current_speed_kmh

        travel_time_hours = remaining_distance / effective_speed
        travel_time_minutes = travel_time_hours * 60.0
        eta = current_time + timedelta(minutes=travel_time_minutes)

        logger.info(
            f"[ETA] Route={route.route_id} TruckDist={truck_road_dist:.2f}km/{total_road_dist:.2f}km "
            f"Rem={remaining_distance:.2f}km Speed={current_speed_kmh}km/h (Eff={effective_speed:.1f}) "
            f"Dur={travel_time_minutes:.1f}m ETA={eta.isoformat()}"
        )

        return {
            "status": "AVAILABLE",
            "effective_speed_kmh": effective_speed,
            "is_stopped": is_stopped,
            "remaining_distance_km": round(remaining_distance, 2),
            "travel_time_minutes": round(travel_time_minutes, 1),
            "eta": eta,
        }

    @staticmethod
    def get_waypoints_eta(
        route: Route,
        current_lat: float,
        current_lon: float,
        current_speed_kmh: float | None,
        current_time: datetime,
        segment_index: int | None = None,
        segment_progress: float | None = None,
    ) -> list[dict]:
        """
        Calculate road distance, travel duration, and ETA for each upcoming waypoint
        along the route.
        """
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        current_time = current_time.astimezone(timezone.utc)

        pts, cum_dists = ETAService._get_road_projections(route)
        truck_road_dist = ETAService._compute_truck_road_distance(
            route, pts, cum_dists, current_lat, current_lon, segment_index, segment_progress
        )

        milestones = [*route.waypoints, route.destination]
        upcoming = []

        is_stopped = current_speed_kmh is None or current_speed_kmh < 5.0
        effective_speed = 45.0 if is_stopped else current_speed_kmh

        for i, m in enumerate(milestones, start=1):
            min_m_dist = float("inf")
            m_idx = 0
            for idx, pt in enumerate(pts):
                d = route.distance_between(pt, m)
                if d < min_m_dist:
                    min_m_dist = d
                    m_idx = idx

            m_road_dist = cum_dists[m_idx]

            # Consider upcoming if not passed by more than 200m
            if m_road_dist >= truck_road_dist - 0.2:
                rem_km = max(0.0, m_road_dist - truck_road_dist)
                travel_mins = (rem_km / effective_speed) * 60.0
                arrival_time = current_time + timedelta(minutes=travel_mins)

                upcoming.append({
                    "waypoint_id": f"{route.route_id}_wp_{i}",
                    "location_name": m.name or f"Station {i}",
                    "latitude": m.latitude,
                    "longitude": m.longitude,
                    "distance_km": round(rem_km, 2),
                    "travel_time_minutes": round(travel_mins, 1),
                    "eta": arrival_time.isoformat(),
                    "expected_arrival_datetime": arrival_time.isoformat(),
                })

        return upcoming
