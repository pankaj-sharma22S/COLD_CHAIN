import json
from database.connection import get_connection
from backend.route import Route, MapPoint, fetch_road_geometry


def _ensure_column(cursor, table: str, column: str, definition: str):
    cursor.execute(
        """SELECT COUNT(*) AS present FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
             AND COLUMN_NAME = %s""",
        (table, column),
    )
    if not cursor.fetchone()[0]:
        cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")


def create_route_tables():
    connection = get_connection()
    cursor = connection.cursor()

    routes_table = """
    CREATE TABLE IF NOT EXISTS routes (
        route_id VARCHAR(100) PRIMARY KEY,

        source_name VARCHAR(255),
        source_latitude DOUBLE NOT NULL,
        source_longitude DOUBLE NOT NULL,

        destination_name VARCHAR(255),
        destination_latitude DOUBLE NOT NULL,
        destination_longitude DOUBLE NOT NULL,

        distance_km DOUBLE DEFAULT 0,
        estimated_duration_minutes DOUBLE DEFAULT 0,

        geometry LONGTEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """

    waypoints_table = """
    CREATE TABLE IF NOT EXISTS route_waypoints (
        waypoint_id BIGINT AUTO_INCREMENT PRIMARY KEY,

        route_id VARCHAR(100) NOT NULL,

        sequence_number INT NOT NULL,

        name VARCHAR(255),

        latitude DOUBLE NOT NULL,
        longitude DOUBLE NOT NULL,

        FOREIGN KEY (route_id)
            REFERENCES routes(route_id)
            ON DELETE CASCADE,

        UNIQUE (route_id, sequence_number)
    )
    """

    cursor.execute(routes_table)
    cursor.execute(waypoints_table)
    _ensure_column(cursor, "routes", "geometry", "LONGTEXT")

    connection.commit()

    cursor.close()
    connection.close()

    print("Route tables are ready.")


def save_route(route: Route):
    """
    Save a Route object into MySQL, including road geometry.
    """
    connection = get_connection()
    cursor = connection.cursor()

    try:
        route.calculate_distance()

        if route.estimated_duration_minutes <= 0:
            route.calculate_estimated_duration()

        geometry_json = json.dumps([
            {"latitude": p.latitude, "longitude": p.longitude, "name": p.name}
            for p in route.road_points
        ])

        route_query = """
        INSERT INTO routes (
            route_id,
            source_name,
            source_latitude,
            source_longitude,
            destination_name,
            destination_latitude,
            destination_longitude,
            distance_km,
            estimated_duration_minutes,
            geometry
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            source_name = VALUES(source_name),
            source_latitude = VALUES(source_latitude),
            source_longitude = VALUES(source_longitude),
            destination_name = VALUES(destination_name),
            destination_latitude = VALUES(destination_latitude),
            destination_longitude = VALUES(destination_longitude),
            distance_km = VALUES(distance_km),
            estimated_duration_minutes = VALUES(estimated_duration_minutes),
            geometry = VALUES(geometry)
        """

        route_values = (
            route.route_id,
            route.source.name,
            route.source.latitude,
            route.source.longitude,
            route.destination.name,
            route.destination.latitude,
            route.destination.longitude,
            route.distance_km,
            route.estimated_duration_minutes,
            geometry_json,
        )

        cursor.execute(route_query, route_values)

        # Clear existing waypoints and insert new ones
        cursor.execute("DELETE FROM route_waypoints WHERE route_id = %s", (route.route_id,))

        waypoint_query = """
        INSERT INTO route_waypoints (
            route_id,
            sequence_number,
            name,
            latitude,
            longitude
        )
        VALUES (%s, %s, %s, %s, %s)
        """

        for sequence, waypoint in enumerate(route.waypoints, start=1):
            waypoint_values = (
                route.route_id,
                sequence,
                waypoint.name,
                waypoint.latitude,
                waypoint.longitude,
            )
            cursor.execute(waypoint_query, waypoint_values)

        connection.commit()
        print(f"Route '{route.route_id}' saved successfully.")

    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def get_route(route_id: str) -> Route | None:
    """
    Load a Route object from MySQL. If road geometry or waypoints are missing,
    fetches OSRM geometry and persists it.
    """
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        route_query = """
        SELECT
            route_id,
            source_name,
            source_latitude,
            source_longitude,
            destination_name,
            destination_latitude,
            destination_longitude,
            distance_km,
            estimated_duration_minutes,
            geometry
        FROM routes
        WHERE route_id = %s
        """

        cursor.execute(route_query, (route_id,))
        route_data = cursor.fetchone()

        if route_data is None:
            return None

        waypoint_query = """
        SELECT
            waypoint_id,
            name,
            latitude,
            longitude
        FROM route_waypoints
        WHERE route_id = %s
        ORDER BY sequence_number
        """

        cursor.execute(waypoint_query, (route_id,))
        waypoint_data = cursor.fetchall()

        waypoints = [
            MapPoint(
                latitude=wp["latitude"],
                longitude=wp["longitude"],
                name=wp["name"],
            )
            for wp in waypoint_data
        ]

        # Seed milestone waypoints for route_001 if empty
        if not waypoints and route_id == "route_001":
            default_milestones = [
                MapPoint(latitude=28.5921, longitude=77.1616, name="Dhaula Kuan"),
                MapPoint(latitude=28.5441, longitude=77.1264, name="Mahipalpur"),
                MapPoint(latitude=28.4952, longitude=77.0891, name="Cyber City"),
                MapPoint(latitude=28.4721, longitude=77.0725, name="IFFCO Chowk"),
            ]
            for seq, mp in enumerate(default_milestones, start=1):
                cursor.execute(
                    """INSERT INTO route_waypoints (route_id, sequence_number, name, latitude, longitude)
                       VALUES (%s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE name=VALUES(name)""",
                    (route_id, seq, mp.name, mp.latitude, mp.longitude),
                )
            connection.commit()
            waypoints = default_milestones

        geometry_points: list[MapPoint] = []
        raw_geom = route_data.get("geometry")

        if raw_geom:
            try:
                parsed_geom = json.loads(raw_geom)
                if isinstance(parsed_geom, list) and len(parsed_geom) >= 2:
                    geometry_points = [
                        MapPoint(
                            latitude=p["latitude"],
                            longitude=p["longitude"],
                            name=p.get("name"),
                        )
                        for p in parsed_geom
                    ]
            except Exception:
                geometry_points = []

        source_pt = MapPoint(
            latitude=route_data["source_latitude"],
            longitude=route_data["source_longitude"],
            name=route_data["source_name"],
        )
        dest_pt = MapPoint(
            latitude=route_data["destination_latitude"],
            longitude=route_data["destination_longitude"],
            name=route_data["destination_name"],
        )

        distance_km = float(route_data["distance_km"] or 0)
        duration_mins = float(route_data["estimated_duration_minutes"] or 0)

        # If geometry is still missing or has only straight endpoints, fetch from OSRM
        if len(geometry_points) < 5:
            geometry_points, distance_km, duration_mins = fetch_road_geometry(
                source_pt, waypoints, dest_pt
            )
            # Persist to MySQL so subsequent loads are instant
            try:
                geom_json = json.dumps([
                    {"latitude": p.latitude, "longitude": p.longitude, "name": p.name}
                    for p in geometry_points
                ])
                cursor.execute(
                    """UPDATE routes
                       SET geometry = %s, distance_km = %s, estimated_duration_minutes = %s
                       WHERE route_id = %s""",
                    (geom_json, distance_km, duration_mins, route_id),
                )
                connection.commit()
            except Exception as err:
                print(f"Could not persist geometry to MySQL: {err}")

        route = Route(
            route_id=route_data["route_id"],
            source=source_pt,
            destination=dest_pt,
            waypoints=waypoints,
            geometry=geometry_points,
            distance_km=distance_km,
            estimated_duration_minutes=duration_mins,
        )

        return route

    finally:
        cursor.close()
        connection.close()


def get_all_routes() -> list[Route]:
    """
    Load all routes from MySQL.
    """
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("SELECT route_id FROM routes ORDER BY created_at")
        route_ids = cursor.fetchall()
        routes = []
        for (route_id,) in route_ids:
            route = get_route(route_id)
            if route is not None:
                routes.append(route)
        return routes
    finally:
        cursor.close()
        connection.close()


def delete_route(route_id: str):
    """
    Delete a route.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM routes WHERE route_id = %s", (route_id,))
        connection.commit()
        print(f"Route '{route_id}' deleted.")
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()
