import os

import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.getenv("DB_NAME", "cold_chain")

SERVER_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
}


def create_database():
    connection = None
    cursor = None

    try:
        connection = mysql.connector.connect(**SERVER_CONFIG)
        cursor = connection.cursor()

        # DB_NAME is configuration, not user input. Backticks handle names
        # that contain reserved words without permitting SQL interpolation.
        query = f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`"
        cursor.execute(query)

        print(f"Database '{DB_NAME}' is ready.")

    except Error as error:
        print(f"Database creation error: {error}")
        raise

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()


def initialize_schema():
    """Create and migrate all application tables idempotently."""
    create_database()
    from database.route_repository import create_route_tables
    from database.telemetry_repository import create_telemetry_table
    from database.trip_repository import create_trip_table
    from database.policy_repository import create_policy_tables
    from database.incident_repository import create_incident_tables

    create_policy_tables()
    create_route_tables()
    create_trip_table()
    create_telemetry_table()
    create_incident_tables()


if __name__ == "__main__":
    initialize_schema()
