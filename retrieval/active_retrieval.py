# backend/retrieval/active_retrieval.py

from datetime import datetime, timedelta
from database.connection import get_connection


DEFAULT_ACTIVE_WINDOW_SECONDS = 60


def _condition_duration_seconds(cursor, truck_id, latest_timestamp, field, predicate):
    """Return the consecutive duration of a condition at the latest sample."""
    cursor.execute(
        f"""SELECT timestamp, {field}
            FROM telemetry
            WHERE truck_id = %s AND timestamp <= %s
            ORDER BY timestamp DESC
            LIMIT 100""",
        (truck_id, latest_timestamp),
    )
    rows = cursor.fetchall()
    if not rows or not predicate(rows[0][field]):
        return 0.0

    first = rows[0]["timestamp"]
    latest = rows[0]["timestamp"]
    for row in rows[1:]:
        if not predicate(row[field]):
            break
        first = row["timestamp"]
    return max(0.0, (latest - first).total_seconds())


def get_active_trucks(active_window_seconds=DEFAULT_ACTIVE_WINDOW_SECONDS):
    """
    Get the latest telemetry for every currently active truck.

    A truck is considered active if it has sent telemetry
    within the active window.

    Returns:
        {
            "timestamp": "...",
            "active_truck_count": 2,
            "active_trucks": [
                {
                    "truck_id": "...",
                    ...
                }
            ]
        }
    """

    connection = get_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cutoff_time = datetime.now() - timedelta(
            seconds=active_window_seconds
        )

        query = """
            SELECT
                t.id,
                t.trip_id,
                t.truck_id,
                t.timestamp,
                t.latitude,
                t.longitude,
                t.speed_kmh,
                t.inside_temperature,
                t.outside_temperature,
                t.humidity,
                t.door_status,
                t.refrigeration_status,
                t.current_point_name,
                t.next_point_name,
                t.segment_index,
                t.segment_progress,
                t.total_distance_km,
                t.route_id,
                t.source_name,
                t.destination_name
            FROM telemetry t
            INNER JOIN (
                SELECT
                    truck_id,
                    MAX(timestamp) AS latest_timestamp
                FROM telemetry
                WHERE timestamp >= %s
                GROUP BY truck_id
            ) latest
                ON t.truck_id = latest.truck_id
                AND t.timestamp = latest.latest_timestamp
            ORDER BY t.truck_id
        """

        cursor.execute(query, (cutoff_time,))
        trucks = cursor.fetchall()

        for truck in trucks:
            truck["door_open_duration_seconds"] = _condition_duration_seconds(
                cursor,
                truck["truck_id"],
                truck["timestamp"],
                "door_status",
                lambda value: value == "OPEN",
            )
            truck["stopped_duration_seconds"] = _condition_duration_seconds(
                cursor,
                truck["truck_id"],
                truck["timestamp"],
                "speed_kmh",
                lambda value: value is not None and value <= 0,
            )
            if truck.get("trip_id"):
                cursor.execute(
                    """SELECT t.cargo_policy_id, t.cargo_type, p.min_temperature, p.max_temperature, p.target_temperature
                       FROM trips t
                       LEFT JOIN cargo_temperature_policies p ON t.cargo_policy_id = p.id
                       WHERE t.trip_id = %s""",
                    (truck["trip_id"],),
                )
                pol = cursor.fetchone()
                if pol:
                    truck["cargo_policy_id"] = pol["cargo_policy_id"]
                    truck["cargo_type"] = pol["cargo_type"]
                    truck["policy_min_temp"] = pol["min_temperature"]
                    truck["policy_max_temp"] = pol["max_temperature"]
                    truck["policy_target_temp"] = pol["target_temperature"]

        return {
            "timestamp": datetime.now().isoformat(),
            "active_truck_count": len(trucks),
            "active_trucks": trucks
        }

    finally:
        cursor.close()
        connection.close()


def get_active_truck(truck_id, active_window_seconds=DEFAULT_ACTIVE_WINDOW_SECONDS):
    """
    Get the latest telemetry for one truck if it is currently active.

    Returns:
        telemetry dictionary, or None if the truck is not active.
    """

    connection = get_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cutoff_time = datetime.now() - timedelta(
            seconds=active_window_seconds
        )

        query = """
            SELECT
                id,
                trip_id,
                truck_id,
                timestamp,
                latitude,
                longitude,
                speed_kmh,
                inside_temperature,
                outside_temperature,
                humidity,
                door_status,
                refrigeration_status,
                current_point_name,
                next_point_name,
                segment_index,
                segment_progress,
                total_distance_km,
                route_id,
                source_name,
                destination_name
            FROM telemetry
            WHERE truck_id = %s
              AND timestamp >= %s
            ORDER BY timestamp DESC
            LIMIT 1
        """

        cursor.execute(query, (truck_id, cutoff_time))
        return cursor.fetchone()

    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    result = get_active_trucks()

    print(f"Active trucks: {result['active_truck_count']}")

    for truck in result["active_trucks"]:
        print(
            truck["truck_id"],
            truck["latitude"],
            truck["longitude"],
            truck["inside_temperature"],
            truck["next_point_name"]
        )
