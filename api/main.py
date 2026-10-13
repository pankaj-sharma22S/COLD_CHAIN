"""Thin HTTP interface; business logic stays in repositories and agent tools."""

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from mysql.connector import Error as MySQLError
from pydantic import BaseModel

from agent.live_graph import run_live_monitoring
from database.trip_repository import get_trip
from database.trip_repository import list_trips
from database.telemetry_repository import get_trip_telemetry, get_truck_telemetry
from database.route_repository import get_route
from backend.fleet_service import get_dashboard_fleet, get_truck_weather
from backend.simulation_controller import simulation_controller
from backend.alert_service import acknowledge_event, list_events, record_agent_action
from database.init_db import initialize_schema
from retrieval.active_retrieval import get_active_truck, get_active_trucks


app = FastAPI(title="Cold-chain AI Agent", version="1.0.0")
_schema_error: str | None = None


@app.on_event("startup")
def initialize_database_on_startup() -> None:
    global _schema_error
    try:
        initialize_schema()
        _schema_error = None
    except Exception as error:
        _schema_error = str(error)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(MySQLError)
async def mysql_error_handler(_, error: MySQLError):
    return JSONResponse(
        status_code=503,
        content={
            "status": "ERROR",
            "error_type": "DATABASE_UNAVAILABLE",
            "message": "Database unavailable or credentials are invalid.",
            "detail": str(error),
        },
    )


class AgentQuery(BaseModel):
    request: str
    truck_id: str | None = None
    trip_id: str | None = None
    thread_id: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok" if _schema_error is None else "degraded"}


def _ensure_schema() -> None:
    global _schema_error
    if _schema_error is None:
        return
    try:
        initialize_schema()
        _schema_error = None
    except Exception as error:
        raise HTTPException(status_code=503, detail="Database schema is unavailable") from error


@app.get("/trucks/active")
def active_trucks() -> dict[str, Any]:
    return get_dashboard_fleet()


@app.get("/simulation")
def simulation_status() -> dict[str, Any]:
    return simulation_controller.status()


@app.post("/simulation/start")
def start_simulation() -> dict[str, Any]:
    try:
        _ensure_schema()
        return simulation_controller.start()
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/simulation/stop")
def stop_simulation() -> dict[str, Any]:
    return simulation_controller.stop()


@app.get("/trucks/{truck_id}")
def truck(truck_id: str) -> dict[str, Any]:
    value = get_active_truck(truck_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Active truck not found")
    return value


@app.get("/trucks/{truck_id}/weather")
def truck_weather(truck_id: str) -> dict[str, Any]:
    return get_truck_weather(truck_id)


@app.get("/trucks/{truck_id}/telemetry")
def truck_telemetry(truck_id: str, hours: float | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    return get_truck_telemetry(truck_id, hours=hours, limit=min(max(limit, 1), 2000))



@app.get("/trips/{trip_id}")
def trip(trip_id: str) -> dict[str, Any]:
    value = get_trip(trip_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    return value


@app.get("/trips")
def trips(status: str | None = None) -> list[dict[str, Any]]:
    return list_trips(status)


@app.get("/trips/{trip_id}/telemetry")
def trip_telemetry(trip_id: str, limit: int = 500) -> list[dict[str, Any]]:
    return get_trip_telemetry(trip_id, min(max(limit, 1), 2000))


@app.get("/routes/{route_id}")
def route(route_id: str) -> dict[str, Any]:
    value = get_route(route_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return value.summary()


@app.post("/agent/query")
def agent_query(query: AgentQuery) -> Any:
    from agent.operations_assistant import ask_operations_assistant
    return ask_operations_assistant(
        request=query.request,
        trip_id=query.trip_id,
        truck_id=query.truck_id,
        thread_id=query.thread_id or (f"{query.truck_id or 'global'}_{query.trip_id or 'main'}"),
    )


@app.post("/agent/chat")
def agent_chat(query: AgentQuery) -> Any:
    from agent.operations_assistant import ask_operations_assistant
    return ask_operations_assistant(
        request=query.request,
        trip_id=query.trip_id,
        truck_id=query.truck_id,
        thread_id=query.thread_id or (f"{query.truck_id or 'global'}_{query.trip_id or 'main'}"),
    )


@app.get("/alerts")
def alerts(
    trip_id: str | None = None,
    current_run_only: bool = False,
    status: str | None = None,
) -> list[dict[str, Any]]:
    if current_run_only:
        sim_status = simulation_controller.status()
        if sim_status.get("status") != "RUNNING":
            return []
        active_trip_ids = [t["trip_id"] for t in sim_status.get("trucks", []) if t.get("trip_id")]
        if not active_trip_ids:
            return []
        return list_events(trip_ids=active_trip_ids, status=status)
    return list_events(trip_id=trip_id, status=status)


@app.post("/alerts/{event_id}/acknowledge")
def acknowledge_alert(event_id: int) -> dict[str, Any]:
    event = acknowledge_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return event


@app.get("/policies")
def get_policies() -> list[dict[str, Any]]:
    from database.policy_repository import list_policies
    return list_policies()


@app.get("/trips/{trip_id}/report")
def completed_trip_report(trip_id: str) -> Any:
    """Generate a report only because this endpoint was explicitly requested."""
    value = get_trip(trip_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    if value.get("status") != "COMPLETED":
        raise HTTPException(
            status_code=400,
            detail=f"Trip '{trip_id}' is not completed (current status: {value.get('status')}). Completed-trip reports can only be generated for completed trips.",
        )
    return run_live_monitoring(
        request=f"Generate the completed trip report for {trip_id}",
        truck_id=value["truck_id"],
        trip_id=trip_id,
    )
