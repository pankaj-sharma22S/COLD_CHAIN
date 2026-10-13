"""Repository for cargo temperature policies."""

from database.connection import get_connection


def create_policy_tables() -> None:
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS cargo_temperature_policies (
                id VARCHAR(50) PRIMARY KEY,
                cargo_type VARCHAR(100) NOT NULL,
                min_temperature DOUBLE NOT NULL,
                max_temperature DOUBLE NOT NULL,
                target_temperature DOUBLE NOT NULL,
                warning_margin DOUBLE NOT NULL DEFAULT 1.0,
                door_open_allowed_seconds INT NOT NULL DEFAULT 60,
                stopped_allowed_seconds INT NOT NULL DEFAULT 300,
                data_loss_allowed_seconds INT NOT NULL DEFAULT 120,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_policy_cargo (cargo_type)
            )"""
        )
        connection.commit()

        # Seed initial policies if empty
        cursor.execute("SELECT COUNT(*) FROM cargo_temperature_policies")
        row = cursor.fetchone()
        count = row[0] if row else 0
        if count == 0:
            seed_data = [
                (
                    "PHARMA_VACCINE",
                    "Pharmaceutical Vaccines & Biologics",
                    2.0,
                    8.0,
                    5.0,
                    1.0,
                    60,
                    300,
                    120,
                    True,
                ),
                (
                    "DEEP_FROZEN",
                    "Deep Frozen Food & Ice Cream",
                    -25.0,
                    -18.0,
                    -20.0,
                    2.0,
                    45,
                    300,
                    120,
                    True,
                ),
                (
                    "FRESH_PRODUCE",
                    "Fresh Produce & Dairy",
                    8.0,
                    12.0,
                    10.0,
                    1.5,
                    90,
                    300,
                    120,
                    True,
                ),
                (
                    "STANDARD_COLD",
                    "Standard Cold Chain",
                    2.0,
                    8.0,
                    5.0,
                    1.0,
                    60,
                    300,
                    120,
                    True,
                ),
            ]
            cursor.executemany(
                """INSERT INTO cargo_temperature_policies
                   (id, cargo_type, min_temperature, max_temperature, target_temperature, warning_margin, door_open_allowed_seconds, stopped_allowed_seconds, data_loss_allowed_seconds, is_active)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                seed_data,
            )
            connection.commit()

        # Safe migration for trips table: add cargo_policy_id and cargo_type if missing
        cursor.execute(
            """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'trips' AND COLUMN_NAME = 'cargo_policy_id'"""
        )
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE trips ADD COLUMN cargo_policy_id VARCHAR(50) DEFAULT 'PHARMA_VACCINE'")
            cursor.execute("ALTER TABLE trips ADD COLUMN cargo_type VARCHAR(100) DEFAULT 'Pharmaceutical Vaccines & Biologics'")
            cursor.execute("UPDATE trips SET cargo_policy_id = 'PHARMA_VACCINE' WHERE cargo_policy_id IS NULL")
            connection.commit()
    finally:
        cursor.close()
        connection.close()


def get_policy(policy_id: str) -> dict | None:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM cargo_temperature_policies WHERE id = %s", (policy_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()


def list_policies() -> list[dict]:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM cargo_temperature_policies WHERE is_active = TRUE ORDER BY id ASC")
        return cursor.fetchall()
    finally:
        cursor.close()
        connection.close()


def get_policy_for_trip(trip_id: str) -> dict | None:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT p.* FROM trips t
               JOIN cargo_temperature_policies p ON t.cargo_policy_id = p.id
               WHERE t.trip_id = %s""",
            (trip_id,),
        )
        row = cursor.fetchone()
        if row:
            return row
        # Fallback to default policy
        return get_policy("PHARMA_VACCINE")
    finally:
        cursor.close()
        connection.close()
