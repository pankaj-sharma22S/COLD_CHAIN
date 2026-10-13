"""LangChain tools for the cold-chain agent."""

from datetime import datetime
from typing import Any

from langchain_core.tools import tool

from retrieval.active_retrieval import (
    get_active_trucks,
)
from retrieval.eta_route_retrieval import (
    get_active_trucks_with_eta,
)
from retrieval.historical_retrieval import (
    get_trip_summary_data,
)
from backend.risk_engine import (
    evaluate_fleet_risk,
)
from retrieval.sop_rag import get_sop
from weather.weather_service import (
    WeatherService,
)


@tool
def get_active_fleet() -> dict[str, Any]:
    """
    Get the latest telemetry for all currently active trucks.

    Use this when current fleet state is required.
    """

    return get_active_trucks()


@tool
def get_fleet_eta() -> dict[str, Any]:
    """
    Get active trucks enriched with route and ETA information.

    Includes:
    - current telemetry
    - next station
    - remaining distance
    - ETA
    """

    return get_active_trucks_with_eta()


@tool
def get_weather_at_eta(
    latitude: float,
    longitude: float,
    requested_time: str,
) -> dict[str, Any]:
    """
    Get weather at a location for a specific arrival time.

    The requested location should normally be the truck's
    next station and requested_time should normally be its ETA.
    """

    return WeatherService.get_weather(
        latitude=latitude,
        longitude=longitude,
        requested_time=datetime.fromisoformat(
            requested_time
        ),
    )


@tool
def evaluate_fleet(
    active_trucks: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Evaluate active trucks using deterministic,
    truck-specific safety rules.

    The LLM must never replace this risk calculation.
    """

    return evaluate_fleet_risk(
        active_trucks
    )


@tool
def retrieve_sop(
    query: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """
    Retrieve relevant cold-chain SOP procedures.

    SOP retrieval provides operational guidance.
    It does not determine the deterministic risk status.
    """

    try:
        documents = get_sop(query=query, top_k=top_k)
    except Exception as error:
        return [{
            "status": "ERROR",
            "error_type": "SOP_RETRIEVAL_UNAVAILABLE",
            "message": str(error),
        }]

    results = []

    for document in documents:
        if isinstance(document, dict):
            results.append(document)
            continue
        results.append(
            {
                "content": document.page_content,
                "metadata": document.metadata,
            }
        )

    return results


@tool
def get_completed_trip(
    truck_id: str | None = None,
    trip_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    """
    Retrieve historical telemetry for a completed trip.

    Prefer trip_id for completed-trip reports; truck_id remains a
    backward-compatible fallback.
    """

    start = (
        datetime.fromisoformat(start_time)
        if start_time
        else None
    )

    end = (
        datetime.fromisoformat(end_time)
        if end_time
        else None
    )

    return get_trip_summary_data(
        truck_id=truck_id,
        trip_id=trip_id,
        start_time=start,
        end_time=end,
    )


def _to_datetime(
    value: Any,
) -> datetime:
    """Convert a timestamp value to datetime."""

    if isinstance(value, datetime):
        return value

    return datetime.fromisoformat(
        str(value)
    )


def _duration_minutes(
    start: Any,
    end: Any,
) -> float:
    """Calculate duration between timestamps."""

    return (
        _to_datetime(end)
        - _to_datetime(start)
    ).total_seconds() / 60.0


def _group_events(
    records: list[dict[str, Any]],
    field: str,
    active_value: Any,
) -> list[dict[str, Any]]:
    """
    Group consecutive active records into events.

    This is deterministic analysis, not LLM reasoning.
    """

    events = []

    start_record = None
    last_record = None

    for record in records:

        active = (
            record.get(field)
            == active_value
        )

        if active and start_record is None:
            start_record = record

        if (
            not active
            and start_record is not None
            and last_record is not None
        ):
            events.append(
                {
                    "start_time": start_record[
                        "timestamp"
                    ],
                    "end_time": last_record[
                        "timestamp"
                    ],
                    "duration_minutes": (
                        _duration_minutes(
                            start_record[
                                "timestamp"
                            ],
                            last_record[
                                "timestamp"
                            ],
                        )
                    ),
                }
            )

            start_record = None

        last_record = record

    if (
        start_record is not None
        and last_record is not None
    ):
        events.append(
            {
                "start_time": start_record[
                    "timestamp"
                ],
                "end_time": last_record[
                    "timestamp"
                ],
                "duration_minutes": (
                    _duration_minutes(
                        start_record[
                            "timestamp"
                        ],
                        last_record[
                            "timestamp"
                        ],
                    )
                ),
            }
        )

    return events


@tool
def analyze_temperature_history(
    records: list[dict[str, Any]],
    truck_id: str,
    min_temp: float | None = None,
    max_temp: float | None = None,
) -> dict[str, Any]:
    """
    Deterministically identify temperature excursions.

    Safe limits come from truck_rules.py or explicit resolved limits.
    """

    from backend.truck_rules import (
        get_temperature_limits,
        get_truck_rules,
    )

    if min_temp is None or max_temp is None:
        limits = get_temperature_limits(truck_id)
        if min_temp is None:
            min_temp = limits.min_temp
        if max_temp is None:
            max_temp = limits.max_temp

    rules = get_truck_rules(
        truck_id
    )

    excursions = []

    current_records = []
    excursion_start = None

    def finish_excursion():
        if (
            excursion_start is None
            or not current_records
        ):
            return

        temperatures = [
            record["inside_temperature"]
            for record in current_records
            if record.get(
                "inside_temperature"
            )
            is not None
        ]

        if not temperatures:
            return

        end_record = current_records[-1]

        direction = (
            "LOW"
            if min(temperatures)
            < min_temp
            else "HIGH"
        )

        duration = _duration_minutes(
            excursion_start["timestamp"],
            end_record["timestamp"],
        )

        severity = "LOW"

        if duration >= 30:
            severity = "MEDIUM"

        if duration >= 60:
            severity = "HIGH"

        if duration >= 120:
            severity = "CRITICAL"

        excursions.append(
            {
                "start_time": (
                    excursion_start["timestamp"]
                ),
                "end_time": (
                    end_record["timestamp"]
                ),
                "duration_minutes": duration,
                "minimum_temperature": min(
                    temperatures
                ),
                "maximum_temperature": max(
                    temperatures
                ),
                "safe_minimum": min_temp,
                "safe_maximum": max_temp,
                "direction": direction,
                "severity": severity,
            }
        )

    for record in records:

        temperature = record.get(
            "inside_temperature"
        )

        if temperature is None:
            continue

        outside_range = (
            temperature
            < min_temp
            or temperature
            > max_temp
        )

        if outside_range:

            if excursion_start is None:
                excursion_start = record

            current_records.append(
                record
            )

        else:

            if excursion_start is not None:
                finish_excursion()

            excursion_start = None
            current_records = []

    if excursion_start is not None:
        finish_excursion()

    return {
        "truck_id": truck_id,
        "safe_range": [
            min_temp,
            max_temp,
        ],
        "excursion_count": len(
            excursions
        ),
        "excursions": excursions,
    }


@tool
def analyze_operational_history(
    records: list[dict[str, Any]],
    truck_id: str,
) -> dict[str, Any]:
    """
    Analyze door, refrigeration and stoppage events.
    """

    from backend.truck_rules import (
        get_truck_rules,
    )

    rules = get_truck_rules(
        truck_id
    )

    door_events = _group_events(
        records,
        "door_status",
        "OPEN",
    )

    refrigeration_events = _group_events(
        records,
        "refrigeration_status",
        "OFF",
    )

    stoppage_events = []

    stopped_start = None
    last_record = None

    for record in records:

        speed = record.get(
            "speed_kmh"
        )

        stopped = (
            speed is not None
            and speed <= 1.0
        )

        if (
            stopped
            and stopped_start is None
        ):
            stopped_start = record

        if (
            not stopped
            and stopped_start is not None
            and last_record is not None
        ):

            duration = _duration_minutes(
                stopped_start[
                    "timestamp"
                ],
                last_record[
                    "timestamp"
                ],
            )

            if (
                duration
                >= rules.stopped_allowed_seconds
                / 60
            ):
                stoppage_events.append(
                    {
                        "start_time": (
                            stopped_start[
                                "timestamp"
                            ]
                        ),
                        "end_time": (
                            last_record[
                                "timestamp"
                            ]
                        ),
                        "duration_minutes": duration,
                        "latitude": (
                            stopped_start.get(
                                "latitude"
                            )
                        ),
                        "longitude": (
                            stopped_start.get(
                                "longitude"
                            )
                        ),
                    }
                )

            stopped_start = None

        last_record = record

    if (
        stopped_start is not None
        and last_record is not None
    ):

        duration = _duration_minutes(
            stopped_start[
                "timestamp"
            ],
            last_record[
                "timestamp"
            ],
        )

        if (
            duration
            >= rules.stopped_allowed_seconds
            / 60
        ):
            stoppage_events.append(
                {
                    "start_time": (
                        stopped_start[
                            "timestamp"
                        ]
                    ),
                    "end_time": (
                        last_record[
                            "timestamp"
                        ]
                    ),
                    "duration_minutes": duration,
                    "latitude": (
                        stopped_start.get(
                            "latitude"
                        )
                    ),
                    "longitude": (
                        stopped_start.get(
                            "longitude"
                        )
                    ),
                }
            )

    return {
        "truck_id": truck_id,
        "door_events": door_events,
        "refrigeration_events": (
            refrigeration_events
        ),
        "stoppage_events": (
            stoppage_events
        ),
    }


LIVE_TOOLS = [
    get_active_fleet,
    get_fleet_eta,
    get_weather_at_eta,
    evaluate_fleet,
]


INVESTIGATION_TOOLS = [
    get_active_fleet,
    get_fleet_eta,
    get_weather_at_eta,
    evaluate_fleet,
    retrieve_sop,
]


REPORT_TOOLS = [
    get_completed_trip,
    analyze_temperature_history,
    analyze_operational_history,
]
