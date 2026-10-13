"""Compatibility entrypoint for explicit completed-trip reports."""

from agent.live_graph import run_live_monitoring
from agent.schemas import TripReport


def run_report(
    request: str,
    truck_id: str | None = None,
    trip_id: str | None = None,
    current_time: str | None = None,
) -> TripReport:
    """Run the existing top-level graph for an explicit report request."""
    if trip_id:
        from database.trip_repository import get_trip
        trip = get_trip(trip_id)
        if trip and trip.get("status") != "COMPLETED":
            raise ValueError(f"Trip '{trip_id}' is not completed (current status: {trip.get('status')}).")
    result = run_live_monitoring(
        request=request,
        truck_id=truck_id,
        trip_id=trip_id,
        current_time=current_time,
    )
    if isinstance(result, TripReport):
        return result
    if isinstance(result, dict) and (result.get("error_type") or result.get("error")):
        raise ValueError(result.get("message") or f"Trip report rejected: {result}")
    return TripReport.model_validate(result)
