import os
import mysql.connector
from mysql.connector import Error, pooling
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "cold_chain"),
}

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        try:
            pool_size = int(os.getenv("DB_POOL_SIZE", "10"))
            _pool = pooling.MySQLConnectionPool(
                pool_name="dispatch_pool",
                pool_size=pool_size,
                pool_reset_session=True,
                **DB_CONFIG,
            )
        except Error as error:
            print(f"Failed to initialize MySQL pool: {error}")
            _pool = None
    return _pool


def get_connection():
    try:
        pool = _get_pool()
        if pool is not None:
            return pool.get_connection()
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            return connection
    except Error as error:
        # Do not include DB_CONFIG here: it may contain a password.
        print(f"MySQL connection error: {error}")
        raise
