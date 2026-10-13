"""Repository operations for trip lifecycle and trip-scoped telemetry."""

from datetime import datetime
from database.connection import get_connection


def create_trip_table() -> None:
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS trips (
                trip_id VARCHAR(100) PRIMARY KEY,
                truck_id VARCHAR(50) NOT NULL,
                route_id VARCHAR(100) NOT NULL,
                cargo_policy_id VARCHAR(50) DEFAULT 'PHARMA_VACCINE',
                cargo_type VARCHAR(100) DEFAULT 'Pharmaceutical Vaccines & Biologics',
                status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
                started_at TIMESTAMP NULL,
                completed_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_trip_truck_status (truck_id, status),
                INDEX idx_trip_route_status (route_id, status),
                INDEX idx_trip_started (started_at)
            )"""
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def create_trip(
    trip_id: str,
    truck_id: str,
    route_id: str,
    started_at: datetime | None = None,
    cargo_policy_id: str = "PHARMA_VACCINE",
    cargo_type: str | None = None,
) -> dict:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        if not cargo_type:
            # Look up policy cargo_type
            cursor.execute("SELECT cargo_type FROM cargo_temperature_policies WHERE id = %s", (cargo_policy_id,))
            p_row = cursor.fetchone()
            cargo_type = p_row["cargo_type"] if p_row else "Pharmaceutical Vaccines & Biologics"

        cursor.execute(
            """INSERT INTO trips (trip_id, truck_id, route_id, cargo_policy_id, cargo_type, status, started_at)
               VALUES (%s, %s, %s, %s, %s, 'ACTIVE', COALESCE(%s, CURRENT_TIMESTAMP))
               ON DUPLICATE KEY UPDATE
                 cargo_policy_id = VALUES(cargo_policy_id),
                 cargo_type = VALUES(cargo_type),
                 status = 'ACTIVE'""",
            (trip_id, truck_id, route_id, cargo_policy_id, cargo_type, started_at),
        )
        connection.commit()
        return get_trip(trip_id, connection=connection)
    finally:
        cursor.close()
        connection.close()


def get_trip(trip_id: str, connection=None) -> dict | None:
    owns_connection = connection is None
    connection = connection or get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM trips WHERE trip_id = %s", (trip_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        if owns_connection:
            connection.close()


def get_active_trip(truck_id: str) -> dict | None:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT * FROM trips WHERE truck_id = %s AND status = 'ACTIVE'
               ORDER BY started_at DESC LIMIT 1""",
            (truck_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()


def list_trips(status: str | None = None) -> list[dict]:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        query = "SELECT * FROM trips"
        params: tuple = ()
        if status:
            query += " WHERE status = %s"
            params = (status,)
        query += " ORDER BY COALESCE(started_at, created_at) DESC"
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        cursor.close()
        connection.close()


def complete_trip(trip_id: str, completed_at: datetime | None = None) -> None:
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """UPDATE trips SET status = 'COMPLETED',
                      completed_at = COALESCE(%s, CURRENT_TIMESTAMP)
               WHERE trip_id = %s""",
            (completed_at, trip_id),
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def cancel_trip(trip_id: str) -> None:
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE trips SET status = 'CANCELLED' WHERE trip_id = %s AND status = 'ACTIVE'",
            (trip_id,),
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()
