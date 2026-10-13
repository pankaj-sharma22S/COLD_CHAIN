"""Historical retrieval for completed-trip analysis."""

from datetime import datetime

from database.connection import get_connection
from database.trip_repository import get_trip


def get_trip_records(
    truck_id,
    trip_id=None,
    start_time=None,
    end_time=None,
):
    """
    Retrieve historical telemetry for a truck.

    Args:
        truck_id: Truck to retrieve.
        start_time: Optional start of trip.
        end_time: Optional end of trip.

    Returns:
        List of telemetry records ordered by timestamp.
    """

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

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
    """

    params = [truck_id]

    if trip_id is not None:
        query = query.replace("WHERE truck_id = %s", "WHERE truck_id = %s AND trip_id = %s")
        params.append(trip_id)

    if start_time is not None:
        query += " AND timestamp >= %s"
        params.append(start_time)

    if end_time is not None:
        query += " AND timestamp <= %s"
        params.append(end_time)

    query += " ORDER BY timestamp ASC"

    try:
        cursor.execute(query, tuple(params))
        records = cursor.fetchall()
        return records

    finally:
        cursor.close()
        connection.close()


def get_trip_summary_data(
    truck_id=None,
    trip_id=None,
    start_time=None,
    end_time=None,
):
    """
    Retrieve the complete dataset required for trip analysis.
    """

    if trip_id:
        trip = get_trip(trip_id)
        if not trip:
            return {
                "trip_id": trip_id,
                "truck_id": truck_id,
                "record_count": 0,
                "records": [],
                "error": "TRIP_NOT_FOUND",
                "message": f"Trip '{trip_id}' not found.",
            }
        if trip.get("status") != "COMPLETED":
            return {
                "trip_id": trip_id,
                "truck_id": trip.get("truck_id") or truck_id,
                "status": trip.get("status"),
                "record_count": 0,
                "records": [],
                "error": "TRIP_NOT_COMPLETED",
                "message": f"Trip '{trip_id}' is not completed (current status: {trip.get('status')}).",
            }
        if not truck_id:
            truck_id = trip.get("truck_id")

    if not truck_id:
        return {"trip_id": trip_id, "record_count": 0, "records": [], "error": "TRUCK_OR_TRIP_REQUIRED"}

    records = get_trip_records(
        truck_id=truck_id,
        trip_id=trip_id,
        start_time=start_time,
        end_time=end_time,
    )

    if not records:
        return {
            "truck_id": truck_id,
            "record_count": 0,
            "records": [],
        }

    return {
        "truck_id": truck_id,
        "trip_id": trip_id,
        "record_count": len(records),
        "trip_start": records[0]["timestamp"],
        "trip_end": records[-1]["timestamp"],
        "route_id": records[0]["route_id"],
        "source_name": records[0]["source_name"],
        "destination_name": records[0]["destination_name"],
        "records": records,
    }


if __name__ == "__main__":
    result = get_trip_summary_data("TRUCK_001")

    print(f"Truck: {result['truck_id']}")
    print(f"Records: {result['record_count']}")
    print(f"Start: {result.get('trip_start')}")
    print(f"End: {result.get('trip_end')}")
