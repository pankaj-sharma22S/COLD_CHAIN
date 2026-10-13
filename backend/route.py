from dataclasses import dataclass, field
from math import radians, sin, cos, sqrt, atan2
from typing import Optional
import requests


@dataclass
class MapPoint:
    latitude: float
    longitude: float
    name: Optional[str] = None


def fetch_road_geometry(
    source: MapPoint,
    waypoints: list[MapPoint],
    destination: MapPoint,
) -> tuple[list[MapPoint], float, float]:
    """
    Fetch actual road-following geometry from OSRM driving service.
    Returns (geometry_points, distance_km, duration_minutes).
    Falls back to straight-line connection if OSRM is unavailable.
    """
    all_points = [source, *waypoints, destination]
    try:
        coords_str = ";".join(f"{p.longitude},{p.latitude}" for p in all_points)
        url = (
            f"http://router.project-osrm.org/route/v1/driving/{coords_str}"
            f"?overview=full&geometries=geojson"
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            routes = data.get("routes")
            if routes and len(routes) > 0:
                first_route = routes[0]
                geometry_coords = first_route.get("geometry", {}).get("coordinates", [])
                if geometry_coords and len(geometry_coords) >= 2:
                    geom_points = [
                        MapPoint(latitude=lat, longitude=lon)
                        for lon, lat in geometry_coords
                    ]
                    # Ensure first and last points retain source and destination names
                    geom_points[0].name = source.name
                    geom_points[-1].name = destination.name

                    distance_km = round(first_route.get("distance", 0.0) / 1000.0, 2)
                    duration_min = round(first_route.get("duration", 0.0) / 60.0, 1)
                    return geom_points, distance_km, duration_min
    except Exception as err:
        print(f"OSRM routing fetch failed, falling back to direct points: {err}")

    # Fallback to direct milestones
    fallback_points = [
        MapPoint(latitude=p.latitude, longitude=p.longitude, name=p.name)
        for p in all_points
    ]
    total_dist = 0.0
    for i in range(len(fallback_points) - 1):
        total_dist += Route.distance_between(fallback_points[i], fallback_points[i + 1])
    return fallback_points, round(total_dist, 2), round((total_dist / 50.0) * 60.0, 1)


@dataclass
class Route:
    route_id: str
    source: MapPoint
    destination: MapPoint

    waypoints: list[MapPoint] = field(default_factory=list)
    geometry: list[MapPoint] = field(default_factory=list)

    distance_km: float = 0.0
    estimated_duration_minutes: float = 0.0

    @property
    def points(self) -> list[MapPoint]:
        """
        Milestone route points (source, intermediate waypoints, destination).
        """
        return [
            self.source,
            *self.waypoints,
            self.destination,
        ]

    @property
    def road_points(self) -> list[MapPoint]:
        """
        Full road-following geometry if available, otherwise milestone points.
        """
        if self.geometry and len(self.geometry) >= 2:
            return self.geometry
        return self.points

    @property
    def segment_count(self) -> int:
        """
        Number of route segments along the road.
        """
        return len(self.road_points) - 1

    def get_segment(self, index: int) -> tuple[MapPoint, MapPoint]:
        """
        Return start and end point of a road segment.
        """
        points = self.road_points

        if index < 0 or index >= len(points) - 1:
            raise IndexError("Invalid segment index")

        return points[index], points[index + 1]

    @staticmethod
    def distance_between(point1: MapPoint, point2: MapPoint) -> float:
        """
        Calculate straight-line distance between two GPS points
        using the Haversine formula.
        """
        earth_radius_km = 6371.0

        lat1 = radians(point1.latitude)
        lat2 = radians(point2.latitude)

        delta_lat = radians(point2.latitude - point1.latitude)
        delta_lon = radians(point2.longitude - point1.longitude)

        a = (
            sin(delta_lat / 2) ** 2
            + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
        )

        c = 2 * atan2(sqrt(a), sqrt(1 - a))

        return earth_radius_km * c

    def segment_distance_km(self, segment_index: int) -> float:
        """
        Calculate distance of one route segment.
        """
        start, end = self.get_segment(segment_index)
        return self.distance_between(start, end)

    def calculate_distance(self) -> float:
        """
        Calculate total route distance.
        """
        total_distance = 0.0
        for index in range(self.segment_count):
            total_distance += self.segment_distance_km(index)

        self.distance_km = round(total_distance, 2)
        return self.distance_km

    def calculate_estimated_duration(
        self,
        average_speed_kmh: float = 50.0,
    ) -> float:
        """
        Estimate route duration using average speed.
        """
        if average_speed_kmh <= 0:
            raise ValueError("Average speed must be greater than 0")

        if self.distance_km == 0:
            self.calculate_distance()

        duration_hours = self.distance_km / average_speed_kmh
        self.estimated_duration_minutes = round(duration_hours * 60, 1)

        return self.estimated_duration_minutes

    def interpolate_position(
        self,
        segment_index: int,
        progress: float,
    ) -> MapPoint:
        """
        Calculate truck position along the current road segment.
        """
        if not 0.0 <= progress <= 1.0:
            raise ValueError("Progress must be between 0.0 and 1.0")

        start, end = self.get_segment(segment_index)

        latitude = (
            start.latitude
            + (end.latitude - start.latitude) * progress
        )

        longitude = (
            start.longitude
            + (end.longitude - start.longitude) * progress
        )

        return MapPoint(
            latitude=latitude,
            longitude=longitude,
        )

    def current_point(
        self,
        segment_index: int,
        progress: float,
    ) -> MapPoint:
        """
        Get the current truck position.
        """
        if self.is_finished(segment_index, progress):
            return self.destination

        return self.interpolate_position(
            segment_index,
            progress,
        )

    def next_point(
        self,
        segment_index: int,
    ) -> Optional[MapPoint]:
        """
        Get the next road point ahead.
        """
        points = self.road_points

        if segment_index + 1 >= len(points):
            return None

        return points[segment_index + 1]

    def is_finished(
        self,
        segment_index: int,
        progress: float,
    ) -> bool:
        """
        Check whether the truck has reached destination.
        """
        return (
            segment_index >= self.segment_count
            or (
                segment_index == self.segment_count - 1
                and progress >= 1.0
            )
        )

    def summary(self) -> dict:
        """
        Return route information in dictionary form including full road geometry.
        """
        return {
            "route_id": self.route_id,
            "source": {
                "name": self.source.name,
                "latitude": self.source.latitude,
                "longitude": self.source.longitude,
            },
            "destination": {
                "name": self.destination.name,
                "latitude": self.destination.latitude,
                "longitude": self.destination.longitude,
            },
            "waypoints": [
                {
                    "name": point.name,
                    "latitude": point.latitude,
                    "longitude": point.longitude,
                }
                for point in self.waypoints
            ],
            "geometry": [
                {
                    "name": point.name,
                    "latitude": point.latitude,
                    "longitude": point.longitude,
                }
                for point in self.road_points
            ],
            "distance_km": self.distance_km,
            "estimated_duration_minutes": self.estimated_duration_minutes,
        }