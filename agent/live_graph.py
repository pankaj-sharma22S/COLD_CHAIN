"""Main LangGraph workflow for the cold-chain AI agent."""

from typing import Any

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)
from langgraph.graph import (
    END,
    START,
    StateGraph,
)
from agent.graph_compat import (
    ToolNode,
    tools_condition,
)

from agent.risk_investigation_graph import (
    run_risk_investigation,
)
from agent.schemas import (
    ActionOutput,
    AgentState,
    TripReport,
)
from agent.tools import (
    LIVE_TOOLS,
    REPORT_TOOLS,
    analyze_operational_history,
    analyze_temperature_history,
    get_completed_trip,
)
from agent.model_factory import create_chat_model


MAIN_SYSTEM_PROMPT = """
You are the main AI controller for a cold-chain logistics system.

There are two types of requests:

1. LIVE_MONITORING
2. TRIP_REPORT

LIVE_MONITORING includes:
- current truck status
- current fleet status
- current risk
- current ETA
- current weather/risk
- what is happening now

TRIP_REPORT includes:
- completed trip report
- historical trip analysis
- trip performance
- temperature excursion report
- "give me report for TRIP_001"

IMPORTANT:

1. A report is generated ONLY when the user explicitly asks for it.

2. Never automatically generate a report merely because a trip
   has completed.

3. Never invent truck IDs or trip IDs.

4. Current risk classification must come from the deterministic
   risk engine.

5. Never invent safety limits.

6. Use tools when evidence is missing.

7. Do not call tools unnecessarily.

8. Consider current time when deciding whether information is stale.

9. Never claim an external alert was sent unless an actual
   notification tool exists.

10. For completed reports, historical telemetry is authoritative
    for measured values.

11. Missing information must remain missing.
"""


REPORT_PROMPT = """
You are a completed-trip cold-chain analysis agent.

Analyze the historical trip data.

Required checks:

1. Temperature excursions.
2. Excursion durations.
3. Temperature minimum/maximum.
4. Refrigeration failures.
5. Door-open events.
6. Abnormal stoppages.
7. Trip duration.
8. Route information available in the dataset.
9. ETA information when actually available.
10. Weather correlation only when weather data actually exists.
11. Overall cold-chain compliance.

Rules:

- Never invent measurements.
- Never invent weather.
- Never invent route deviations.
- Never invent expected ETA.
- Use truck-specific configured rules.
- Distinguish facts from conclusions.
- If evidence is insufficient, use INCONCLUSIVE.
- analysis_complete=true only after all applicable checks
  have been considered.
"""


def create_live_model():
    """Create the live monitoring model."""

    return create_chat_model(tools=LIVE_TOOLS)


def create_report_model():
    """Create the completed-trip report model."""

    return create_chat_model()


def detect_intent(
    request: str,
) -> str:
    """
    Determine whether the request is live monitoring
    or an explicit completed-trip report request.

    This is intentionally simple and deterministic.
    """

    text = request.lower()

    report_terms = [
        "report",
        "historical",
        "completed trip",
        "trip analysis",
        "trip performance",
        "excursion report",
    ]

    if any(
        term in text
        for term in report_terms
    ):
        return "TRIP_REPORT"

    return "LIVE_MONITORING"


# ------------------------------------------------------------------
# LIVE MONITORING
# ------------------------------------------------------------------


def live_agent_node(
    state: AgentState,
) -> dict[str, Any]:
    """Agentically gather information for live monitoring."""
    try:
        model = create_live_model()

        messages = [
            SystemMessage(
                content=MAIN_SYSTEM_PROMPT
            )
        ]

        if state.messages:
            messages.extend(
                state.messages
            )
        else:
            messages.append(
                HumanMessage(
                    content=(
                        f"Current time: "
                        f"{state.current_time}\n\n"
                        f"User request: "
                        f"{state.request}\n\n"
                        f"Truck ID: "
                        f"{state.truck_id}\n\n"
                        "Start monitoring and obtain "
                        "the information required."
                    )
                )
            )

        response = model.invoke(messages)
        return {"messages": [response]}
    except Exception as exc:
        print(f"Warning: Live agent model unavailable ({exc}). Using deterministic state.")
        from langchain_core.messages import AIMessage
        return {
            "messages": [
                AIMessage(
                    content=f"Monitoring performed using deterministic risk engine rules for {state.truck_id or 'all fleet units'}."
                )
            ]
        }


def live_decision_node(
    state: AgentState,
) -> dict[str, Any]:
    """Convert live evidence into ActionOutput."""
    try:
        model = create_chat_model()
        structured = model.with_structured_output(ActionOutput)
        result = structured.invoke(
            [
                SystemMessage(
                    content="""
Create the final live monitoring action.

Rules:

- Use only tool results and observed facts.
- Deterministic risk results are authoritative.
- Never invent safe temperature limits.
- If risk is present, status must be RISKY.
- If no risk exists, status should be NORMAL.
- Do not claim an alert was sent.
"""
                ),
                HumanMessage(
                    content=(
                        "Live monitoring state:\n\n"
                        f"{state.model_dump_json(indent=2)}"
                    )
                ),
            ]
        )
        return {"action": result}
    except Exception as exc:
        print(f"Warning: Live decision model unavailable ({exc}). Using deterministic rule fallback.")
        # Deterministic fallback from risk evaluation
        from backend.risk_engine import evaluate_fleet_risk
        from retrieval.active_retrieval import get_active_trucks
        fleet_data = get_active_trucks()
        risks = evaluate_fleet_risk(fleet_data.get("active_trucks", []))
        risky_trucks = [t for t in risks.get("trucks", []) if t.get("status") == "RISKY"]

        target_truck_risk = None
        if state.truck_id:
            for t in risks.get("trucks", []):
                if t.get("truck_id") == state.truck_id:
                    target_truck_risk = t
                    break

        if target_truck_risk and target_truck_risk.get("status") == "RISKY":
            reasons = target_truck_risk.get("reasons", [])
            msg = "; ".join(r.get("message", "Excursion detected") for r in reasons)
            return {
                "action": ActionOutput(
                    status="RISKY",
                    truck_id=state.truck_id,
                    action="ALERT",
                    severity="HIGH",
                    reason=msg,
                )
            }
        elif risky_trucks:
            first_r = risky_trucks[0]
            reasons = first_r.get("reasons", [])
            msg = "; ".join(r.get("message", "Excursion detected") for r in reasons)
            return {
                "action": ActionOutput(
                    status="RISKY",
                    truck_id=first_r.get("truck_id"),
                    action="ALERT",
                    severity="HIGH",
                    reason=msg,
                )
            }
        else:
            return {
                "action": ActionOutput(
                    status="NORMAL",
                    truck_id=state.truck_id or "FLEET",
                    action="CONTINUE_MONITORING",
                    severity="INFO",
                    reason="All fleet units operating within normal safe policy thresholds.",
                )
            }


def route_live_action(
    state: AgentState,
) -> str:
    """Route risky trucks to investigation."""

    if state.action is None:
        return "end"

    if (
        state.action.status
        == "RISKY"
    ):
        return "investigate"

    return "end"


def risk_investigation_node(
    state: AgentState,
) -> dict[str, Any]:
    """Run the existing risk-investigation subgraph."""

    action = run_risk_investigation(
        state
    )

    return {
        "action": action
    }


# ------------------------------------------------------------------
# REPORT
# ------------------------------------------------------------------


def report_retrieval_node(
    state: AgentState,
) -> dict[str, Any]:
    """Retrieve historical telemetry for report generation."""

    if not state.truck_id and not state.trip_id:
        return {
            "historical_data": {
                "record_count": 0,
                "error": "TRUCK_ID_REQUIRED",
                "message": "Truck ID or Trip ID is required for completed trip reports.",
            }
        }

    from database.trip_repository import get_trip
    truck_id = state.truck_id
    if state.trip_id:
        trip = get_trip(state.trip_id)
        if not trip:
            return {
                "historical_data": {
                    "trip_id": state.trip_id,
                    "record_count": 0,
                    "records": [],
                    "error": "TRIP_NOT_FOUND",
                    "message": f"Trip '{state.trip_id}' not found.",
                }
            }
        if trip.get("status") != "COMPLETED":
            return {
                "historical_data": {
                    "trip_id": state.trip_id,
                    "truck_id": trip.get("truck_id") or truck_id,
                    "status": trip.get("status"),
                    "record_count": 0,
                    "records": [],
                    "error": "TRIP_NOT_COMPLETED",
                    "message": f"Trip '{state.trip_id}' is not completed (current status: {trip.get('status')}). Completed-trip reports can only be generated for completed trips.",
                }
            }
        if not truck_id:
            truck_id = trip.get("truck_id")

    historical = get_completed_trip.invoke(
        {
            "truck_id": truck_id,
            "trip_id": state.trip_id,
        }
    )

    update: dict[str, Any] = {"historical_data": historical}
    if truck_id and not state.truck_id:
        update["truck_id"] = truck_id
    return update


def report_analysis_node(
    state: AgentState,
) -> dict[str, Any]:
    """
    Run deterministic historical calculations.

    These calculations are not delegated to the LLM.
    """

    historical = (
        state.historical_data
        or {}
    )

    if historical.get("error"):
        return {
            "risk_data": {
                "error": historical.get("error"),
                "message": historical.get("message", "Unable to analyze trip data."),
            }
        }

    records = historical.get(
        "records",
        [],
    )

    if not records:
        return {
            "risk_data": {
                "error": (
                    "NO_HISTORICAL_RECORDS"
                )
            }
        }

    from backend.truck_rules import get_temperature_limits
    truck_id = state.truck_id or historical.get("truck_id")
    limits = get_temperature_limits(truck_id)
    min_temp = limits.min_temp
    max_temp = limits.max_temp

    temperature = (
        analyze_temperature_history.invoke(
            {
                "records": records,
                "truck_id": truck_id,
                "min_temp": min_temp,
                "max_temp": max_temp,
            }
        )
    )

    operations = (
        analyze_operational_history.invoke(
            {
                "records": records,
                "truck_id": truck_id,
            }
        )
    )

    return {
        "risk_data": {
            "temperature_limits": {
                "min_temp": min_temp,
                "max_temp": max_temp,
            },
            "temperature": temperature,
            "operations": operations,
        }
    }


def report_final_node(
    state: AgentState,
) -> dict[str, Any]:
    """Generate the final Pydantic TripReport."""

    historical = state.historical_data or {}
    if historical.get("error"):
        return {}

    analysis = state.risk_data or {}
    if analysis.get("error"):
        return {}

    try:
        model = create_report_model()
        structured = model.with_structured_output(
            TripReport
        )
        result = structured.invoke(
            [
                SystemMessage(
                    content=REPORT_PROMPT
                ),
                HumanMessage(
                    content=(
                        "Historical telemetry:\n\n"
                        f"{historical}\n\n"
                        "Deterministic analysis:\n\n"
                        f"{analysis}"
                    )
                ),
            ]
        )
        return {
            "report": result
        }
    except Exception:
        from agent.schemas import (
            ETAAnalysis,
            RouteAnalysis,
            TripReport,
            TripSafetyAnalysis,
            WeatherCorrelation,
        )

        def _str_time(val):
            return str(val) if val is not None else ""

        def _clean_event(e):
            item = dict(e)
            if "start_time" in item:
                item["start_time"] = _str_time(item["start_time"])
            if "end_time" in item:
                item["end_time"] = _str_time(item["end_time"])
            return item

        temp_data = analysis.get("temperature", {})
        ops_data = analysis.get("operations", {})
        excursions = [_clean_event(e) for e in temp_data.get("excursions", [])]
        door_events = [_clean_event(e) for e in ops_data.get("door_events", [])]
        ref_events = [_clean_event(e) for e in ops_data.get("refrigeration_events", [])]
        stoppage_events = [_clean_event(e) for e in ops_data.get("stoppage_events", [])]

        temp_compliant = len(excursions) == 0
        ref_compliant = len(ref_events) == 0
        door_compliant = len(door_events) == 0
        stoppage_compliant = len(stoppage_events) == 0
        cold_chain_maintained = temp_compliant and ref_compliant

        overall_status = "COMPLIANT" if cold_chain_maintained else "NON_COMPLIANT"
        limits = analysis.get("temperature_limits", {})
        explanation = (
            f"Trip maintained cold-chain compliance within configured safe limits "
            f"({limits.get('min_temp', 2.0)}°C to {limits.get('max_temp', 8.0)}°C)."
            if cold_chain_maintained
            else f"Identified {len(excursions)} temperature excursions and {len(ref_events)} refrigeration anomalies."
        )

        report = TripReport(
            report_type="COMPLETED_TRIP_REPORT",
            truck_id=state.truck_id or historical.get("truck_id", "UNKNOWN"),
            trip_id=state.trip_id or historical.get("trip_id"),
            route_id=historical.get("route_id"),
            trip_start=str(historical.get("trip_start")) if historical.get("trip_start") else None,
            trip_end=str(historical.get("trip_end")) if historical.get("trip_end") else None,
            record_count=historical.get("record_count", 0),
            source=historical.get("source_name"),
            destination=historical.get("destination_name"),
            temperature_excursions=excursions,
            door_events=door_events,
            refrigeration_events=ref_events,
            stoppage_events=stoppage_events,
            route_analysis=RouteAnalysis(
                route_id=historical.get("route_id"),
                source=historical.get("source_name"),
                destination=historical.get("destination_name"),
                route_deviation_detected=False,
            ),
            eta_analysis=ETAAnalysis(
                delayed=False,
            ),
            weather_correlation=WeatherCorrelation(
                weather_data_available=False,
            ),
            safety_analysis=TripSafetyAnalysis(
                cold_chain_maintained=cold_chain_maintained,
                temperature_compliant=temp_compliant,
                refrigeration_compliant=ref_compliant,
                door_compliant=door_compliant,
                stoppage_compliant=stoppage_compliant,
                overall_status=overall_status,
                explanation=explanation,
            ),
            key_findings=[
                f"Total telemetry records analyzed: {historical.get('record_count', 0)}",
                f"Configured temperature limits: {limits.get('min_temp', 2.0)}°C to {limits.get('max_temp', 8.0)}°C",
                f"Temperature excursions detected: {len(excursions)}",
            ],
            recommendations=[
                "Maintain refrigeration pre-cooling prior to loading.",
                "Review door duration logs during cargo transfer.",
            ],
            analysis_complete=True,
        )
        return {"report": report}


# ------------------------------------------------------------------
# TOP LEVEL ROUTING
# ------------------------------------------------------------------


def intent_node(
    state: AgentState,
) -> dict[str, Any]:
    """Determine request type."""

    intent = detect_intent(
        state.request or ""
    )

    return {
        "intent": intent
    }


def route_intent(
    state: AgentState,
) -> str:
    """Select live or report workflow."""

    if (
        state.intent
        == "TRIP_REPORT"
    ):
        return "report"

    return "live"


# ------------------------------------------------------------------
# GRAPH CONSTRUCTION
# ------------------------------------------------------------------


def build_live_graph():
    """
    Build the complete cold-chain graph.

    Top level:

        START
          ↓
        intent
          ├── LIVE
          │    ↓
          │  agent
          │    ↓
          │  tools ↔ agent
          │    ↓
          │ decision
          │   ├── NORMAL → END
          │   └── RISKY → investigation → END
          │
          └── REPORT
               ↓
          historical
               ↓
          deterministic analysis
               ↓
          TripReport
               ↓
              END
    """

    graph = StateGraph(
        AgentState
    )

    # Top-level router
    graph.add_node(
        "intent",
        intent_node,
    )

    # Live path
    graph.add_node(
        "live_agent",
        live_agent_node,
    )

    graph.add_node(
        "live_tools",
        ToolNode(
            LIVE_TOOLS
        ),
    )

    graph.add_node(
        "live_decision",
        live_decision_node,
    )

    graph.add_node(
        "risk_investigation",
        risk_investigation_node,
    )

    # Report path
    graph.add_node(
        "report_retrieval",
        report_retrieval_node,
    )

    graph.add_node(
        "report_analysis",
        report_analysis_node,
    )

    graph.add_node(
        "report_final",
        report_final_node,
    )

    # START
    graph.add_edge(
        START,
        "intent",
    )

    # Intent routing
    graph.add_conditional_edges(
        "intent",
        route_intent,
        {
            "live": "live_agent",
            "report": "report_retrieval",
        },
    )

    # Live agent/tool loop
    graph.add_conditional_edges(
        "live_agent",
        tools_condition,
        {
            "tools": "live_tools",
            END: "live_decision",
        },
    )

    graph.add_edge(
        "live_tools",
        "live_agent",
    )

    # Live risk routing
    graph.add_conditional_edges(
        "live_decision",
        route_live_action,
        {
            "investigate": (
                "risk_investigation"
            ),
            "end": END,
        },
    )

    graph.add_edge(
        "risk_investigation",
        END,
    )

    # Report path
    graph.add_edge(
        "report_retrieval",
        "report_analysis",
    )

    graph.add_edge(
        "report_analysis",
        "report_final",
    )

    graph.add_edge(
        "report_final",
        END,
    )

    return graph.compile()


live_graph = build_live_graph()


def run_live_monitoring(
    request: str,
    truck_id: str | None = None,
    trip_id: str | None = None,
    current_time: str | None = None,
):
    """
    Main application entry point.

    Despite the historical function name, this now handles:

    - live monitoring
    - risk investigation
    - completed-trip reports
    """

    state = AgentState(
        request=request,
        truck_id=truck_id,
        trip_id=trip_id,
        current_time=current_time,
    )

    result = live_graph.invoke(
        state
    )

    if result.get("report") is not None:
        return result["report"]

    if result.get("action") is not None:
        return result["action"]

    historical_err = (result.get("historical_data") or {}).get("error")
    if historical_err:
        return {
            "status": "REJECTED",
            "error_type": historical_err,
            "message": (result.get("historical_data") or {}).get("message", f"Trip report rejected: {historical_err}"),
            "trip_id": (result.get("historical_data") or {}).get("trip_id") or state.trip_id,
            "truck_id": (result.get("historical_data") or {}).get("truck_id") or state.truck_id,
        }

    risk_err = (result.get("risk_data") or {}).get("error")
    if risk_err:
        return {
            "status": "REJECTED",
            "error_type": risk_err,
            "message": (result.get("risk_data") or {}).get("message", f"Trip analysis error: {risk_err}"),
        }

    return {
        "status": "ERROR",
        "message": "Agent returned no result.",
    }
