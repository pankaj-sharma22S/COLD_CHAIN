import requests
import os
import math
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from threading import RLock

load_dotenv()


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


class WeatherService:
    FORECAST_URL = os.getenv(
        "WEATHER_FORECAST_URL", "https://api.open-meteo.com/v1/forecast"
    )
    HISTORICAL_URL = os.getenv(
        "WEATHER_HISTORICAL_URL", "https://archive-api.open-meteo.com/v1/archive"
    )
    CACHE_KM_TOLERANCE = float(os.getenv("WEATHER_CACHE_KM_TOLERANCE", "10.0"))
    CACHE_MINUTES_TOLERANCE = float(os.getenv("WEATHER_CACHE_MINUTES_TOLERANCE", "60.0"))

    _cache: list[dict] = []
    _lock = RLock()

    @staticmethod
    def get_weather(latitude: float, longitude: float, requested_time: datetime) -> dict:
        """
        Get weather for a specific place and time using a strict CACHE-FIRST policy.
        Matches against both geographic distance (Haversine <= CACHE_KM_TOLERANCE)
        and complete datetime (year, month, day, hour).
        """
        if requested_time.tzinfo is None:
            requested_time = requested_time.replace(tzinfo=timezone.utc)
        requested_time = requested_time.astimezone(timezone.utc)

        with WeatherService._lock:
            best_match = None
            min_score = float("inf")

            for record in WeatherService._cache:
                rec_time = datetime.fromisoformat(record["weather_datetime"])
                # Match complete datetime: difference must fall within hourly tolerance (3600 seconds)
                time_diff_sec = abs((requested_time - rec_time).total_seconds())
                if time_diff_sec <= max(3600.0, WeatherService.CACHE_MINUTES_TOLERANCE * 60.0):
                    dist = haversine_distance(latitude, longitude, record["latitude"], record["longitude"])
                    if dist <= WeatherService.CACHE_KM_TOLERANCE:
                        # Score combines distance and time difference
                        score = dist * 100.0 + time_diff_sec
                        if score < min_score:
                            min_score = score
                            best_match = record

            if best_match is not None:
                # Return standard dict copy enriched with requested_time
                res = dict(best_match)
                res["requested_time"] = requested_time.isoformat()
                return res

        # Cache miss - perform external Open-Meteo call
        print(f"Cache miss for {latitude:.4f}, {longitude:.4f} at {requested_time.isoformat()}")
        date = requested_time.strftime("%Y-%m-%d")
        hour_str = requested_time.strftime("%Y-%m-%dT%H:00")
        now = datetime.now(timezone.utc)

        if requested_time < now - timedelta(days=1):
            url = WeatherService.HISTORICAL_URL
        else:
            url = WeatherService.FORECAST_URL

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join([
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation",
                "rain",
                "wind_speed_10m",
                "weather_code",
            ]),
            "timezone": "UTC",
        }

        if requested_time < now - timedelta(days=1):
            params["start_date"] = date
            params["end_date"] = date
        else:
            params["forecast_days"] = 16

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
        except requests.RequestException as error:
            return {
                "status": "ERROR",
                "error_type": "WEATHER_UNAVAILABLE",
                "message": str(error),
                "latitude": latitude,
                "longitude": longitude,
                "requested_time": requested_time.isoformat(),
            }

        data = response.json()
        hourly = data.get("hourly")
        if not hourly or "time" not in hourly:
            return {
                "status": "ERROR",
                "error_type": "WEATHER_UNAVAILABLE",
                "message": "No hourly weather data returned.",
                "latitude": latitude,
                "longitude": longitude,
                "requested_time": requested_time.isoformat(),
            }

        times = hourly["time"]
        fetched_at_iso = datetime.now(timezone.utc).isoformat()

        # Cache hourly records returned for this location
        matched_result = None
        min_target_diff = float("inf")

        with WeatherService._lock:
            for i, t_str in enumerate(times):
                t_dt = datetime.fromisoformat(t_str.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
                record = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "weather_datetime": t_dt.isoformat(),
                    "weather_time": t_str,
                    "temperature_c": hourly["temperature_2m"][i],
                    "humidity_percent": hourly["relative_humidity_2m"][i],
                    "precipitation_mm": hourly["precipitation"][i] if "precipitation" in hourly else 0.0,
                    "rain_mm": hourly["rain"][i] if "rain" in hourly else 0.0,
                    "wind_speed_kmh": hourly["wind_speed_10m"][i] if "wind_speed_10m" in hourly else 0.0,
                    "weather_code": hourly["weather_code"][i] if "weather_code" in hourly else 0,
                    "fetched_at": fetched_at_iso,
                    "source": "OPEN_METEO",
                }
                WeatherService._cache.append(record)

                diff = abs((requested_time - t_dt).total_seconds())
                if diff < min_target_diff:
                    min_target_diff = diff
                    matched_result = record

            # Bound cache size to prevent unbounded memory growth
            if len(WeatherService._cache) > 2000:
                WeatherService._cache = WeatherService._cache[-2000:]

        if matched_result is not None:
            res = dict(matched_result)
            res["requested_time"] = requested_time.isoformat()
            return res

        return {
            "status": "ERROR",
            "error_type": "WEATHER_UNAVAILABLE",
            "message": "No matching hourly period found.",
            "latitude": latitude,
            "longitude": longitude,
            "requested_time": requested_time.isoformat(),
        }


if __name__ == "__main__":
    now_utc = datetime.now(timezone.utc)
    weather = WeatherService.get_weather(
        latitude=31.1048,
        longitude=77.1734,
        requested_time=now_utc,
    )
    print(f"Dynamic Weather at {now_utc.isoformat()}:")
    print(weather)
