from database.connection import get_connection


def create_telemetry_table():
    connection = get_connection()
    cursor = connection.cursor()

    query = """
    CREATE TABLE IF NOT EXISTS telemetry (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,

        trip_id VARCHAR(100),
        truck_id VARCHAR(50) NOT NULL,

        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        latitude DOUBLE NOT NULL,
        longitude DOUBLE NOT NULL,

        speed_kmh DOUBLE,

        inside_temperature DOUBLE,
        outside_temperature DOUBLE,

        humidity DOUBLE,

        door_status VARCHAR(20),
        refrigeration_status VARCHAR(20),

        current_point_name VARCHAR(255),
        next_point_name VARCHAR(255),

        segment_index INT,
        segment_progress DOUBLE,

        total_distance_km DOUBLE,

        route_id VARCHAR(100),

        source_name VARCHAR(255),
        destination_name VARCHAR(255),

        FOREIGN KEY (trip_id) REFERENCES trips(trip_id),

        INDEX idx_truck_timestamp (truck_id, timestamp),
        INDEX idx_trip_timestamp (trip_id, timestamp)
    )
    """

    cursor.execute(query)
    _ensure_column(cursor, "telemetry", "trip_id", "VARCHAR(100)")
    _ensure_trip_foreign_key(cursor)
    connection.commit()

    cursor.close()
    connection.close()

    print("Telemetry table is ready.")


def _ensure_column(cursor, table: str, column: str, definition: str):
    cursor.execute(
        """SELECT COUNT(*) AS present FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
             AND COLUMN_NAME = %s""",
        (table, column),
    )
    if not cursor.fetchone()[0]:
        cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")


def _ensure_trip_foreign_key(cursor):
    cursor.execute(
        """SELECT COUNT(*) AS present FROM information_schema.REFERENTIAL_CONSTRAINTS
           WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'fk_telemetry_trip'"""
    )
    if not cursor.fetchone()[0]:
        try:
            cursor.execute(
                "ALTER TABLE telemetry ADD CONSTRAINT fk_telemetry_trip "
                "FOREIGN KEY (trip_id) REFERENCES trips(trip_id)"
            )
        except Exception:
            # Existing legacy rows may contain trip IDs not yet migrated.
            # Keep telemetry usable; new installations get the FK above.
            pass


def insert_telemetry(data: dict):
    connection = get_connection()
    cursor = connection.cursor()

    current_point = data.get("current_point")
    next_point = data.get("next_point")

    query = """
    INSERT INTO telemetry (
        trip_id,
        truck_id,
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
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s
    )
    """

    values = (
        data.get("trip_id"),
        data["truck_id"],
        data["latitude"],
        data["longitude"],
        data["speed_kmh"],
        data["inside_temperature"],
        data["outside_temperature"],
        data["humidity"],
        data["door_status"],
        data["refrigeration_status"],

        current_point["name"] if current_point else None,
        next_point["name"] if next_point else None,

        data["segment_index"],
        data["segment_progress"],
        data["total_distance_km"],

        data["route_id"],
        data["source"],
        data["destination"],
    )

    cursor.execute(query, values)
    connection.commit()

    cursor.close()
    connection.close()


def get_trip_telemetry(trip_id: str, limit: int = 500) -> list[dict]:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT * FROM telemetry WHERE trip_id = %s
               ORDER BY timestamp DESC LIMIT %s""",
            (trip_id, limit),
        )
        rows = cursor.fetchall()
        return list(reversed(rows))
    finally:
        cursor.close()
        connection.close()


def get_truck_telemetry(truck_id: str, hours: float | None = None, limit: int = 1000) -> list[dict]:
    """Retrieve historical telemetry for a truck, optionally filtered by hours window."""
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        from datetime import datetime, timedelta
        if hours and hours > 0:
            cutoff = datetime.now() - timedelta(hours=hours)
            cursor.execute(
                """SELECT * FROM telemetry WHERE truck_id = %s AND timestamp >= %s
                   ORDER BY timestamp ASC LIMIT %s""",
                (truck_id, cutoff, limit),
            )
            return cursor.fetchall()
        else:
            cursor.execute(
                """SELECT * FROM telemetry WHERE truck_id = %s
                   ORDER BY timestamp DESC LIMIT %s""",
                (truck_id, limit),
            )
            rows = cursor.fetchall()
            return list(reversed(rows))
    finally:
        cursor.close()
        connection.close()

