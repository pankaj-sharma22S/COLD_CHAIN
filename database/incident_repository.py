"""Repository for persistent incident lifecycle and audit tracking."""

from datetime import datetime, timezone
from typing import Any
from database.connection import get_connection


def create_incident_tables() -> None:
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS incidents (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                trip_id VARCHAR(100) NOT NULL,
                truck_id VARCHAR(50) NOT NULL,
                risk_type VARCHAR(50) NOT NULL,
                severity VARCHAR(20) NOT NULL DEFAULT 'MEDIUM',
                status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
                message TEXT NOT NULL,
                current_value DOUBLE NULL,
                threshold_violated VARCHAR(100) NULL,
                fingerprint VARCHAR(100) NOT NULL,
                first_detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_observed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                acknowledged_at TIMESTAMP NULL,
                resolved_at TIMESTAMP NULL,
                INDEX idx_incident_trip_status (trip_id, status),
                INDEX idx_incident_truck_status (truck_id, status),
                INDEX idx_incident_fingerprint (fingerprint),
                INDEX idx_incident_status (status)
            )"""
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def upsert_incident(
    trip_id: str,
    truck_id: str,
    risk_type: str,
    severity: str,
    message: str,
    current_value: float | None = None,
    threshold_violated: str | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """
    If an ACTIVE incident with the same (trip_id, truck_id, risk_type) exists,
    update last_observed_at, message, and current_value.
    Otherwise, insert a new ACTIVE incident record.
    """
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    fingerprint = f"{truck_id}_{trip_id}_{risk_type}"
    now = observed_at or datetime.now(timezone.utc)

    try:
        cursor.execute(
            """SELECT * FROM incidents
               WHERE trip_id = %s AND truck_id = %s AND risk_type = %s AND status = 'ACTIVE'
               LIMIT 1""",
            (trip_id, truck_id, risk_type),
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                """UPDATE incidents
                   SET last_observed_at = %s,
                       message = %s,
                       current_value = %s,
                       severity = %s,
                       threshold_violated = %s
                   WHERE id = %s""",
                (now, message, current_value, severity, threshold_violated, existing["id"]),
            )
            connection.commit()
            existing["last_observed_at"] = now
            existing["message"] = message
            existing["current_value"] = current_value
            existing["severity"] = severity
            existing["threshold_violated"] = threshold_violated
            return existing
        else:
            cursor.execute(
                """INSERT INTO incidents
                   (trip_id, truck_id, risk_type, severity, status, message, current_value, threshold_violated, fingerprint, first_detected_at, last_observed_at)
                   VALUES (%s, %s, %s, %s, 'ACTIVE', %s, %s, %s, %s, %s, %s)""",
                (trip_id, truck_id, risk_type, severity, message, current_value, threshold_violated, fingerprint, now, now),
            )
            connection.commit()
            new_id = cursor.lastrowid
            return {
                "id": new_id,
                "trip_id": trip_id,
                "truck_id": truck_id,
                "risk_type": risk_type,
                "severity": severity,
                "status": "ACTIVE",
                "message": message,
                "current_value": current_value,
                "threshold_violated": threshold_violated,
                "fingerprint": fingerprint,
                "first_detected_at": now,
                "last_observed_at": now,
                "acknowledged_at": None,
                "resolved_at": None,
            }
    finally:
        cursor.close()
        connection.close()


def resolve_missing_incidents(
    trip_id: str,
    truck_id: str,
    active_risk_types: set[str],
    resolved_at: datetime | None = None,
) -> list[int]:
    """
    Mark active incidents for this trip/truck as RESOLVED if their risk_type is
    no longer present in active_risk_types.
    """
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    now = resolved_at or datetime.now(timezone.utc)
    resolved_ids = []

    try:
        cursor.execute(
            """SELECT id, risk_type FROM incidents
               WHERE trip_id = %s AND truck_id = %s AND status IN ('ACTIVE', 'ACKNOWLEDGED')""",
            (trip_id, truck_id),
        )
        rows = cursor.fetchall()

        for row in rows:
            if row["risk_type"] not in active_risk_types:
                cursor.execute(
                    """UPDATE incidents
                       SET status = 'RESOLVED', resolved_at = %s
                       WHERE id = %s""",
                    (now, row["id"]),
                )
                resolved_ids.append(row["id"])

        if resolved_ids:
            connection.commit()
        return resolved_ids
    finally:
        cursor.close()
        connection.close()


def acknowledge_incident(incident_id: int) -> dict[str, Any] | None:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    now = datetime.now(timezone.utc)
    try:
        cursor.execute(
            """UPDATE incidents
               SET status = 'ACKNOWLEDGED', acknowledged_at = %s
               WHERE id = %s""",
            (now, incident_id),
        )
        connection.commit()
        cursor.execute("SELECT * FROM incidents WHERE id = %s", (incident_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()


def resolve_trip_incidents(trip_id: str, resolved_at: datetime | None = None) -> int:
    """Mark all active/acknowledged incidents for this trip as RESOLVED."""
    connection = get_connection()
    cursor = connection.cursor()
    now = resolved_at or datetime.now(timezone.utc)
    try:
        cursor.execute(
            """UPDATE incidents
               SET status = 'RESOLVED', resolved_at = %s
               WHERE trip_id = %s AND status IN ('ACTIVE', 'ACKNOWLEDGED')""",
            (now, trip_id),
        )
        connection.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        connection.close()


def resolve_all_active_incidents(resolved_at: datetime | None = None) -> int:
    """Clean up dangling active incidents from prior simulator runs."""
    connection = get_connection()
    cursor = connection.cursor()
    now = resolved_at or datetime.now(timezone.utc)
    try:
        cursor.execute(
            """UPDATE incidents
               SET status = 'RESOLVED', resolved_at = %s
               WHERE status IN ('ACTIVE', 'ACKNOWLEDGED')""",
            (now,),
        )
        connection.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        connection.close()


def list_incidents(
    status: str | None = None,
    truck_id: str | None = None,
    trip_id: str | None = None,
    trip_ids: list[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        query = "SELECT * FROM incidents"
        conditions = []
        params = []

        if status:
            conditions.append("status = %s")
            params.append(status)
        if truck_id:
            conditions.append("truck_id = %s")
            params.append(truck_id)
        if trip_id:
            conditions.append("trip_id = %s")
            params.append(trip_id)
        elif trip_ids:
            placeholders = ", ".join(["%s"] * len(trip_ids))
            conditions.append(f"trip_id IN ({placeholders})")
            params.extend(trip_ids)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY last_observed_at DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, tuple(params))
        return cursor.fetchall()
    finally:
        cursor.close()
        connection.close()
