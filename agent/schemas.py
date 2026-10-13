"""Pydantic schemas for the cold-chain agent."""

from typing import Any, Annotated, Literal, Optional

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class ActionOutput(BaseModel):
    """Final action produced by the live monitoring agent."""

    status: Literal[
        "NORMAL",
        "RISKY",
        "ERROR",
    ]

    action: Literal[
        "NO_ACTION",
        "CONTINUE_MONITORING",
        "ALERT",
        "NOTIFY_OPERATOR",
        "INVESTIGATE",
        "REQUEST_HUMAN_REVIEW",
        "GENERATE_REPORT",
    ]

    severity: Literal[
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    ]

    truck_id: Optional[str] = None

    reason: str

    recommended_actions: list[str] = Field(
        default_factory=list
    )

    requires_human: bool = False


class TemperatureExcursion(BaseModel):
    """Temperature excursion during a completed trip."""

    start_time: str

    end_time: str

    duration_minutes: float

    minimum_temperature: Optional[float] = None

    maximum_temperature: Optional[float] = None

    safe_minimum: float

    safe_maximum: float

    direction: Literal[
        "LOW",
        "HIGH",
    ]

    severity: Literal[
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    ]


class DoorEvent(BaseModel):
    """Door-open event."""

    start_time: str

    end_time: str

    duration_minutes: float


class RefrigerationEvent(BaseModel):
    """Refrigeration failure event."""

    start_time: str

    end_time: str

    duration_minutes: float

    status: Literal["OFF"]


class StoppageEvent(BaseModel):
    """Abnormal vehicle stoppage."""

    start_time: str

    end_time: str

    duration_minutes: float

    latitude: Optional[float] = None

    longitude: Optional[float] = None


class RouteAnalysis(BaseModel):
    """Completed-trip route analysis."""

    route_id: Optional[str] = None

    source: Optional[str] = None

    destination: Optional[str] = None

    planned_distance_km: Optional[float] = None

    observed_distance_km: Optional[float] = None

    route_deviation_detected: bool = False


class ETAAnalysis(BaseModel):
    """Completed-trip ETA analysis."""

    expected_duration_minutes: Optional[float] = None

    actual_duration_minutes: Optional[float] = None

    delay_minutes: Optional[float] = None

    delayed: bool = False


class WeatherCorrelation(BaseModel):
    """Weather relationship with trip conditions."""

    weather_data_available: bool = False

    observed_weather_effect: Optional[str] = None

    supporting_factors: list[str] = Field(
        default_factory=list
    )


class TripSafetyAnalysis(BaseModel):
    """Overall cold-chain compliance."""

    cold_chain_maintained: bool

    temperature_compliant: bool

    refrigeration_compliant: bool

    door_compliant: bool

    stoppage_compliant: bool

    overall_status: Literal[
        "COMPLIANT",
        "NON_COMPLIANT",
        "INCONCLUSIVE",
    ]

    explanation: str


class TripReport(BaseModel):
    """Final on-demand completed-trip report."""

    report_type: Literal[
        "COMPLETED_TRIP_REPORT"
    ] = "COMPLETED_TRIP_REPORT"

    truck_id: str

    trip_id: Optional[str] = None

    route_id: Optional[str] = None

    trip_start: Optional[str] = None

    trip_end: Optional[str] = None

    record_count: int

    source: Optional[str] = None

    destination: Optional[str] = None

    temperature_excursions: list[
        TemperatureExcursion
    ] = Field(
        default_factory=list
    )

    door_events: list[DoorEvent] = Field(
        default_factory=list
    )

    refrigeration_events: list[
        RefrigerationEvent
    ] = Field(
        default_factory=list
    )

    stoppage_events: list[StoppageEvent] = Field(
        default_factory=list
    )

    route_analysis: RouteAnalysis

    eta_analysis: ETAAnalysis

    weather_correlation: WeatherCorrelation

    safety_analysis: TripSafetyAnalysis

    key_findings: list[str] = Field(
        default_factory=list
    )

    recommendations: list[str] = Field(
        default_factory=list
    )

    analysis_complete: bool = False


class AgentState(BaseModel):
    """
    Shared state for all LangGraph workflows.

    The same state is used for:
    - live monitoring
    - risk investigation
    - completed-trip reporting
    """

    request: Optional[str] = None

    current_time: Optional[str] = None

    truck_id: Optional[str] = None

    trip_id: Optional[str] = None

    active_trucks: list[dict[str, Any]] = Field(
        default_factory=list
    )

    selected_truck: Optional[
        dict[str, Any]
    ] = None

    eta_data: Optional[
        dict[str, Any]
    ] = None

    weather_data: Optional[
        dict[str, Any]
    ] = None

    risk_data: Optional[
        dict[str, Any]
    ] = None

    historical_data: Optional[
        dict[str, Any]
    ] = None

    sop_data: Optional[Any] = None

    action: Optional[ActionOutput] = None

    report: Optional[TripReport] = None

    intent: Optional[
        Literal[
            "LIVE_MONITORING",
            "TRIP_REPORT",
        ]
    ] = None

    messages: Annotated[
        list[AnyMessage],
        add_messages,
    ] = Field(
        default_factory=list
    )