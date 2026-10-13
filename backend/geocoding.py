"""Reverse geocoding with in-memory caching to resolve human-readable location names."""

import requests
from threading import RLock

_GEO_CACHE: dict[str, str] = {}
_GEO_LOCK = RLock()


def get_location_name(latitude: float, longitude: float, default_name: str | None = None) -> str:
    """
    Resolve human-readable location name for given coordinates.
    Caches results so Nominatim is never repeatedly called for the same coordinates.
    """
    if default_name and not default_name.startswith("Point_") and not default_name.startswith("Waypoint_") and not default_name.startswith("Station_"):
        return default_name

    cache_key = f"{round(latitude, 3)}_{round(longitude, 3)}"
    with _GEO_LOCK:
        if cache_key in _GEO_CACHE:
            return _GEO_CACHE[cache_key]

    try:
        headers = {"User-Agent": "ColdChainDispatch/1.0 (dispatch-control@local)"}
        resp = requests.get(
            f"https://nominatim.openstreetmap.org/reverse?lat={latitude}&lon={longitude}&format=json",
            headers=headers,
            timeout=3,
        )
        if resp.status_code == 200:
            data = resp.json()
            addr = data.get("address", {})
            name = (
                addr.get("suburb")
                or addr.get("neighbourhood")
                or addr.get("city")
                or addr.get("town")
                or addr.get("village")
                or addr.get("state_district")
                or (data.get("display_name", "").split(",")[0].strip() if data.get("display_name") else None)
            )
            if name:
                with _GEO_LOCK:
                    _GEO_CACHE[cache_key] = name
                return name
    except Exception:
        pass

    fallback = default_name or f"{round(latitude, 4)}, {round(longitude, 4)}"
    with _GEO_LOCK:
        _GEO_CACHE[cache_key] = fallback
    return fallback
