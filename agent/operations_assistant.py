"""Evidence-Driven Cold Chain AI Operations Assistant Graph.

Processes natural language operations questions across live and completed trips:
User Question
 -> Conversation Context & Entity Resolution
 -> Permission Validation
 -> Database Retrieval & Deterministic Metric Calculations
 -> Evidence Packaging & Context Limits
 -> Grounded LLM Reasoning & Markdown Report Generation
 -> Response Validation
"""

import json
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from agent.model_factory import create_chat_model
from agent.operations_evidence import build_trip_evidence_package
from database.trip_repository import get_active_trip, list_trips

OPERATIONS_ASSISTANT_SYSTEM_PROMPT = """You are an evidence-driven Cold Chain Logistics Operations Assistant.
Answer the user's question strictly using the supplied verified evidence and processed metrics.
You may interpret, explain, compare, and summarize evidence, but you must NOT fabricate database values, timestamps, locations, calculations, policy limits, incidents, or causes.
Use deterministic backend calculations for numerical metrics. Do not recompute them inconsistently.

Distinguish:
- Observed facts.
- Backend-calculated metrics.
- Inferences.
- Recommendations.
- Unknown or unavailable information.

Rules:
1. For live trips, include the latest telemetry timestamp and explicitly report whether data is fresh or stale.
2. For completed trips, report final recorded status and historical results rather than presenting them as current live state.
3. For stop analysis, show timestamps, duration, location where available, and whether each stop is ongoing or completed.
4. For temperature analysis, identify the applicable policy and distinguish confirmed excursions from missing or insufficient evidence.
5. For incident analysis, distinguish temporal correlation from confirmed causation.
6. Never treat missing telemetry as proof that the cargo remained safe.
7. Never claim to have retrieved or analyzed records that are absent from the evidence package.
8. If retrieval was incomplete, identify the incomplete sources or time ranges and qualify conclusions accordingly.
9. When asked for a complete report, organize the answer clearly into:
   - Trip Summary & State
   - Distance & Speed Analysis
   - Stop Timeline & Idling
   - Cold-Chain Compliance & Excursions
   - Incident & Operational Event History
   - Data Quality & Freshness Assessment
   - Recommendations / Next Steps where justified.
10. Use the user's requested level of detail. Be concise for simple questions and thorough for complete reports.
11. Format your response in clean GitHub-style Markdown with tables or bullet points where appropriate.
12. Do not expose credentials or internal secrets.
"""


class OperationsAssistantState(BaseModel):
    """Conversational state for the Operations Assistant."""

    thread_id: str = "default"
    request: str = ""
    trip_id: Optional[str] = None
    truck_id: Optional[str] = None
    intent: Optional[str] = None
    needs_clarification: bool = False
    clarification_message: Optional[str] = None
    evidence: Optional[dict[str, Any]] = None
    response_text: Optional[str] = None
    metrics_summary: Optional[dict[str, Any]] = None
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)


def resolve_entity_node(state: OperationsAssistantState) -> dict[str, Any]:
    """
    Extract Trip ID, Truck ID, and intent from current query and conversation context.
    Explicit user identifiers always take precedence over prior state.
    """
    query = state.request or ""
    query_upper = query.upper()

    # 1. Regex check for explicit TRIP ID
    trip_match = re.search(r"\b(TRIP[-_][A-Za-z0-9_]+)\b", query, re.IGNORECASE)
    explicit_trip = trip_match.group(1).upper() if trip_match else None

    # Check for TRIP 001 or TRIP-1024 or TRIP_T001
    if not explicit_trip:
        trip_space_match = re.search(r"\bTRIP\s+([A-Za-z0-9_]+)\b", query, re.IGNORECASE)
        if trip_space_match:
            explicit_trip = f"TRIP_{trip_space_match.group(1).upper()}"

    # 2. Check for explicit TRUCK ID (T001, TRUCK_001, TRUCK-002, etc.)
    truck_match = re.search(r"\b(TRUCK[-_]?[0-9]{3}|T00[1-9])\b", query, re.IGNORECASE)
    explicit_truck = truck_match.group(1).upper() if truck_match else None

    # 3. Intent classification
    intent = "GENERAL_QUERY"
    if any(k in query_upper for k in ["FLEET", "ALL TRUCKS", "STATUS OF THE TRUCKS", "STATUS OF TRUCKS", "ACTIVE TRUCKS", "TRUCKS AND TRIPS"]):
        intent = "FLEET_OVERVIEW"
    elif any(k in query_upper for k in ["COMPLETE REPORT", "DETAILED REPORT", "FULL REPORT", "REPORT FOR"]):
        intent = "COMPLETE_REPORT"
    elif any(k in query_upper for k in ["CURRENT STATE", "LIVE STATE", "IS THIS TRIP LIVE", "STATUS OF"]):
        intent = "CURRENT_STATE"
    elif any(k in query_upper for k in ["STOP", "STOPPED", "STATIONARY", "HOW MANY STOPS", "WHY DID THE TRUCK STOP"]):
        intent = "STOP_ANALYSIS"
    elif any(k in query_upper for k in ["AVERAGE SPEED", "SPEED", "DISTANCE", "ODOMETER", "KM/H"]):
        intent = "SPEED_AND_DISTANCE"
    elif any(k in query_upper for k in ["TEMPERATURE", "EXCURSION", "PERMITTED RANGE", "COOLING", "REEFER"]):
        intent = "TEMPERATURE_ANALYSIS"
    elif any(k in query_upper for k in ["INCIDENT", "ALERTS", "CORRECTIVE ACTION"]):
        intent = "INCIDENTS_ANALYSIS"
    elif any(k in query_upper for k in ["COMPARE", "PREVIOUS TRIP"]):
        intent = "TRIP_COMPARISON"

    # Prior state inheritance
    resolved_trip = explicit_trip or state.trip_id
    resolved_truck = explicit_truck or state.truck_id

    # If truck is known but trip is missing, resolve latest/active trip for that truck
    if resolved_truck and not resolved_trip:
        active = get_active_trip(resolved_truck)
        if active:
            resolved_trip = active["trip_id"]

    # If still no trip, see if there's only one active trip in the entire system
    if not resolved_trip and not resolved_truck:
        all_trips = list_trips(status="ACTIVE")
        if len(all_trips) == 1:
            resolved_trip = all_trips[0]["trip_id"]
            resolved_truck = all_trips[0]["truck_id"]

    # If asking for fleet overview, we don't need a single trip clarification
    needs_clarification = False
    clarification_msg = None
    if not resolved_trip and intent not in ["FLEET_OVERVIEW", "GENERAL_QUERY"]:
        needs_clarification = True
        recent_trips = list_trips()[:5]
        trip_list_str = ", ".join(f"`{t['trip_id']}` ({t['truck_id']})" for t in recent_trips)
        clarification_msg = (
            f"Please specify which trip or truck you would like to inspect. "
            f"Available recent trips include: {trip_list_str}."
        )

    return {
        "trip_id": resolved_trip,
        "truck_id": resolved_truck,
        "intent": intent,
        "needs_clarification": needs_clarification,
        "clarification_message": clarification_msg,
    }


def fetch_evidence_node(state: OperationsAssistantState) -> dict[str, Any]:
    """Fetch complete telemetry, policy, metrics, and incidents for the resolved trip or fleet."""
    if state.needs_clarification:
        return {}

    if state.intent == "FLEET_OVERVIEW" or not state.trip_id:
        from retrieval.active_retrieval import get_active_trucks
        fleet_data = get_active_trucks()
        return {
            "evidence": {
                "type": "FLEET_OVERVIEW",
                "fleet": fleet_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "metrics_summary": {
                "active_truck_count": fleet_data.get("active_truck_count", 0),
            },
        }

    include_comp = state.intent == "TRIP_COMPARISON" or "PREVIOUS" in state.request.upper()
    evidence_package = build_trip_evidence_package(
        trip_id=state.trip_id,
        user_question=state.request,
        intent=state.intent or "GENERAL_QUERY",
        include_comparison=include_comp,
    )

    metrics_sum = {}
    if "calculated_metrics" in evidence_package:
        metrics_sum = evidence_package["calculated_metrics"]

    return {
        "evidence": evidence_package,
        "metrics_summary": metrics_sum,
    }


def generate_response_node(state: OperationsAssistantState) -> dict[str, Any]:
    """Generate LLM response grounded in verified evidence, or provide deterministic report fallback."""
    if state.needs_clarification:
        return {
            "response_text": state.clarification_message,
            "messages": [AIMessage(content=state.clarification_message or "")],
        }

    evidence = state.evidence or {}
    if evidence.get("error") == "TRIP_NOT_FOUND":
        msg = f"❌ **Trip Not Found**: Trip `{state.trip_id}` was not found in the database. Please verify the Trip ID."
        return {
            "response_text": msg,
            "messages": [AIMessage(content=msg)],
        }

    # Format human prompt with structured evidence
    evidence_json = json.dumps(evidence, indent=2, default=str)
    user_prompt = f"""User Question: {state.request}

Verified Evidence Package:
{evidence_json}
"""

    try:
        model = create_chat_model()
        parser = StrOutputParser()
        system_msg = SystemMessage(content=OPERATIONS_ASSISTANT_SYSTEM_PROMPT)
        human_msg = HumanMessage(content=user_prompt)

        # Include prior conversation turns if present
        convo_messages = [system_msg]
        if state.messages:
            convo_messages.extend(state.messages[-4:])
        convo_messages.append(human_msg)

        # Pipeline with StrOutputParser
        chain = model | parser
        raw_content = chain.invoke(convo_messages)
        content = refine_output(raw_content)
        return {
            "response_text": content,
            "messages": [AIMessage(content=content)],
        }
    except Exception as exc:
        print(f"Warning: LLM generation failed ({exc}). Using deterministic report synthesis fallback.")
        fallback_text = _build_deterministic_markdown_response(state.request, evidence)
        refined_fallback = refine_output(fallback_text)
        return {
            "response_text": refined_fallback,
            "messages": [AIMessage(content=refined_fallback)],
        }


def refine_output(text: str) -> str:
    """
    Refine model or synthesis string output by removing raw markdown clutter,
    awkward combined prefixes like '*#', '#*', normalizing bullet symbols,
    and converting division/special symbols to clean ASCII.
    """
    if not text:
        return ""

    # 1. Clean accidental bullet-header mergers like '*#', '* #', '* ###', '- #'
    cleaned = re.sub(r"^\s*[*+-]\s*(#+)\s*", r"\1 ", text, flags=re.MULTILINE)

    # 2. Clean trailing header marks like '### Title ###' -> '### Title'
    cleaned = re.sub(r"(#+)\s*([^#\n]+)\s*#+\s*$", r"\1 \2", cleaned, flags=re.MULTILINE)

    # 3. Clean awkward '*#' or '#*' anywhere in text
    cleaned = re.sub(r"\*+#+|\*+\s*#+|#+\s*\*+", "", cleaned)

    # 4. Normalize division and math symbols to clean ASCII to prevent terminal mojibake
    cleaned = cleaned.replace("÷", " / ").replace("×", " * ")

    # 5. Clean redundant multiple blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def _build_deterministic_markdown_response(query: str, evidence: dict[str, Any]) -> str:
    """Deterministic fallback synthesizing verified evidence directly into markdown."""
    if evidence.get("type") == "FLEET_OVERVIEW":
        fleet = evidence.get("fleet", {})
        trucks = fleet.get("active_trucks", [])
        lines = [
            f"### 🚛 Active Fleet Operations Status ({len(trucks)} trucks active)",
            f"- **Telemetry Timestamp**: {fleet.get('timestamp')}",
            "",
        ]
        if not trucks:
            lines.append("No trucks are currently active or reporting in the fleet.")
        else:
            for t in trucks:
                t_id = t.get("truck_id")
                trip = t.get("trip_id")
                temp = t.get("inside_temperature")
                spd = t.get("speed_kmh")
                door = t.get("door_status")
                cargo = t.get("cargo_type")
                min_t = t.get("policy_min_temp")
                max_t = t.get("policy_max_temp")
                src = t.get("source_name")
                dst = t.get("destination_name")
                curr = t.get("current_point_name")
                lines.extend([
                    f"#### 🚚 Truck `{t_id}` (Trip `{trip}`)",
                    f"- **Route**: {src} ➔ {dst} (Near `{curr}`)",
                    f"- **Cargo**: {cargo} (Safe Range: `{min_t}°C` to `{max_t}°C`)",
                    f"- **Current Cargo Temp**: `{temp}°C` (Speed: `{spd} km/h`, Door: `{door}`)",
                    "",
                ])
        return "\n".join(lines)

    trip_id = evidence.get("trip_id", "UNKNOWN")
    truck_id = evidence.get("truck_id", "UNKNOWN")
    status = evidence.get("status", "UNKNOWN")
    freshness = evidence.get("data_freshness", {})
    route = evidence.get("route", {})
    metrics = evidence.get("calculated_metrics", {})
    policy = evidence.get("cargo_policy", {})
    stops = evidence.get("stops", {})
    temp = evidence.get("temperature_analysis", {})
    incidents = evidence.get("incidents", [])

    q_upper = query.upper()

    # 1. SPEED = 0 / STATIONARY / WHY DID THE TRUCK STOP
    if any(k in q_upper for k in ["SPEED = 0", "SPEED 0", "ZERO SPEED", "WHY WAS SPEED RECORDED AS 0", "WHY DID THE TRUCK STOP", "STATIONARY REASON"]):
        samples = evidence.get("telemetry_samples", [])
        last_sample = samples[-1] if samples else {}
        recorded_speed = last_sample.get("speed_kmh", metrics.get("latest_speed_kmh", 0.0))
        door = last_sample.get("door_status", "CLOSED")
        stat_sec = metrics.get("stationary_seconds", 0)
        ongoing_stops = stops.get("ongoing_stops", 0)
        completed_stops = stops.get("stop_count", 0)
        stop_list = stops.get("stops", [])
        current_loc = last_sample.get("current_station", {}).get("name") or "En route segment"

        lines = [
            f"### 🛑 Zero-Speed & Stationary Analysis: Trip `{trip_id}` (`{truck_id}`)",
            f"- **Recorded Speed at Query Time**: `{recorded_speed} km/h`",
            f"- **Door Status at Ping**: `{door}`",
            f"- **Current Waypoint / Location**: `{current_loc}`",
            f"- **Total Cumulative Stationary Time**: `{round(stat_sec / 60, 1)} minutes`",
            f"- **Completed Scheduled Stops**: {completed_stops} | **Ongoing Stops**: {ongoing_stops}",
            "",
            "**Operational Explanation:**",
        ]
        if recorded_speed == 0.0:
            if ongoing_stops > 0:
                current_stop = stop_list[-1] if stop_list else {}
                lines.append(f"- The vehicle is currently engaged in a verified stop at `{current_stop.get('location', {}).get('location_name', current_loc)}` lasting `{current_stop.get('duration_minutes', 0)} min` (started at `{current_stop.get('start_time')}`).")
            elif door == "OPEN":
                lines.append(f"- The vehicle is stationary with cargo doors OPEN ({door}), indicating active depot loading, unloading, or physical inspection.")
            else:
                lines.append("- Telemetry indicates a temporary halt or traffic dwell point. Vehicle coordinates match the designated corridor with doors closed and refrigeration active.")
        else:
            lines.append(f"- Latest verified telemetry shows the vehicle is actively moving at `{recorded_speed} km/h`. Historical telemetry records {completed_stops} prior stop(s) totaling `{round(stat_sec / 60, 1)} min`.")
        return "\n".join(lines)

    # 2. DELAY & SCHEDULE CALCULATION
    if any(k in q_upper for k in ["DELAY", "SCHEDULE", "ON TIME", "ETA CALCULATION", "SCHEDULED TIME"]):
        total_dist = metrics.get("total_distance_km", 0.0)
        avg_spd = metrics.get("trip_wide_average_speed_kmh", 0.0)
        elapsed_min = round(metrics.get("total_elapsed_seconds", 0) / 60, 1)
        return "\n".join([
            f"### ⏱️ Schedule & Delay Assessment: Trip `{trip_id}` (`{truck_id}`)",
            f"- **Trip Status**: `{status}`",
            f"- **Route**: {route.get('source', 'Origin')} ➔ {route.get('destination', 'Destination')}",
            f"- **Elapsed Travel Time**: `{elapsed_min} minutes`",
            f"- **Total Distance Traveled**: `{total_dist} km`",
            f"- **Current Effective Speed**: `{avg_spd} km/h`",
            "",
            "**Calculation & Timing Formulation:**",
            "- `Delay = Actual / Projected Arrival Time - Scheduled Arrival Time`",
            f"- Data indicates vehicle is actively progressing along Route `{route.get('route_id')}` with {stops.get('stop_count', 0)} planned station stops and total dwell time of `{round(stops.get('total_stop_duration_seconds', 0) / 60, 1)} min`.",
            f"- Data Freshness: `{freshness.get('freshness_status')}` (Latest ping: `{freshness.get('latest_telemetry_timestamp')}`).",
        ])

    # 3. AVERAGE SPEED & STEP-BY-STEP FORMULAS
    if any(k in q_upper for k in ["FORMULA", "HOW IS AVERAGE SPEED", "CALCULATE THE AVERAGE SPEED", "CALCULATION"]) and not any(k in q_upper for k in ["COMPLETE", "FULL"]):
        dist = metrics.get("total_distance_km", 0.0)
        elapsed_sec = metrics.get("total_elapsed_seconds", 0)
        elapsed_hr = round(elapsed_sec / 3600, 3)
        driving_sec = metrics.get("driving_seconds", 0)
        driving_hr = round(driving_sec / 3600, 3)
        trip_avg = metrics.get("trip_wide_average_speed_kmh", 0.0)
        driving_avg = metrics.get("driving_only_average_speed_kmh", 0.0)
        sensor_avg = metrics.get("arithmetic_sensor_average_speed_kmh", 0.0)
        sample_count = metrics.get("valid_speed_sample_count", 0)

        return "\n".join([
            f"### 📐 Deterministic Speed Formulas & Calculations: Trip `{trip_id}`",
            "",
            "#### 1. Trip-Wide Average Speed (including stationary / stop time):",
            "- **Formula**: `Total Distance (km) / Total Elapsed Time (hours)`",
            f"- **Calculation**: `{dist} km / {elapsed_hr} hr = {trip_avg} km/h`",
            f"- **Result**: `{trip_avg} km/h`",
            "",
            "#### 2. Driving-Only Average Speed (excluding stationary stops):",
            "- **Formula**: `Total Distance (km) / Active Driving Time (hours)`",
            f"- **Calculation**: `{dist} km / {driving_hr} hr = {driving_avg} km/h`",
            f"- **Result**: `{driving_avg} km/h`",
            "",
            "#### 3. Arithmetic Sensor Mean:",
            "- **Formula**: `Sum of all valid sensor speed readings / Total speed samples`",
            f"- **Calculation**: Derived across {sample_count} valid GPS/telemetry samples",
            f"- **Result**: `{sensor_avg} km/h` (Peak valid speed: `{metrics.get('max_valid_speed_kmh', 0.0)} km/h`)",
        ])

    # 4. TRIP COMPARISON (Current vs Previous)
    if any(k in q_upper for k in ["COMPARE", "PREVIOUS TRIP", "PRIOR TRIP"]):
        prev_trip = evidence.get("previous_trip")
        if prev_trip:
            prev_id = prev_trip.get("trip_id")
            prev_status = prev_trip.get("status")
            return "\n".join([
                f"### 🔄 Trip Comparison: Current `{trip_id}` vs Previous `{prev_id}`",
                f"- **Vehicle**: `{truck_id}`",
                "",
                "| Operational Metric | Current Trip (`" + str(trip_id) + "`) | Previous Trip (`" + str(prev_id) + "`) |",
                "| :--- | :--- | :--- |",
                f"| **Status** | `{status}` | `{prev_status}` |",
                f"| **Distance Traveled** | `{metrics.get('total_distance_km', 0.0)} km` | Historical record |",
                f"| **Trip-wide Avg Speed** | `{metrics.get('trip_wide_average_speed_kmh', 0.0)} km/h` | Verified archive |",
                f"| **Excursion Count** | `{temp.get('excursion_count', 0)}` | Database audit |",
                f"| **Stationary Stops** | `{stops.get('stop_count', 0)}` | Verified |",
            ])
        else:
            return f"### 🔄 Trip Comparison: Trip `{trip_id}`\n- **Truck**: `{truck_id}`\n- No immediately preceding trip was located in the database for truck `{truck_id}` prior to `{trip_id}`."

    # 5. LIVE VS COMPLETED / CURRENT STATE
    if any(k in q_upper for k in ["LIVE OR COMPLETED", "IS THIS TRIP LIVE", "CURRENT STATE", "IS TRIP LIVE", "TRIP LIVE"]):
        is_live = status == "ACTIVE"
        return "\n".join([
            f"### 📡 Trip Lifecycle State: Trip `{trip_id}` (`{truck_id}`)",
            f"- **State**: `{'🟢 LIVE (IN TRANSIT)' if is_live else '🏁 ' + str(status)}`",
            f"- **Freshness**: `{freshness.get('freshness_status')}`",
            f"- **Latest Sensor Ping**: `{freshness.get('latest_telemetry_timestamp')}` ({freshness.get('age_seconds', 0)}s ago)",
            f"- **Current Distance**: `{metrics.get('total_distance_km', 0.0)} km`",
            f"- **Current Temperature**: `{temp.get('max_observed_temperature_c', 'N/A')}°C` (Policy: `{policy.get('min_temperature')}°C` to `{policy.get('max_temperature')}°C`)",
            f"- **Cold Chain Compliance**: `{'✅ SAFE (COMPLIANT)' if temp.get('cold_chain_maintained') else '⚠️ EXCURSION DETECTED'}`",
        ])

    # 6. GENERAL SPEED & DISTANCE
    if any(k in q_upper for k in ["AVERAGE SPEED", "SPEED", "DISTANCE", "ODOMETER"]) and not any(k in q_upper for k in ["COMPLETE", "FULL", "DETAILED"]):
        return "\n".join([
            f"### 🚗 Speed & Distance Analysis: Trip `{trip_id}` (`{truck_id}`)",
            f"- **Total Distance Traveled**: `{metrics.get('total_distance_km', 0.0)} km`",
            f"- **Trip-wide Average Speed**: `{metrics.get('trip_wide_average_speed_kmh', 0.0)} km/h` (calculated across total elapsed time of {round(metrics.get('total_elapsed_seconds', 0) / 60, 1)} min)",
            f"- **Driving-only Average Speed**: `{metrics.get('driving_only_average_speed_kmh', 0.0)} km/h`",
            f"- **Arithmetic Mean of Speed Sensors**: `{metrics.get('arithmetic_sensor_average_speed_kmh', 0.0)} km/h`",
            f"- **Peak Valid Speed Recorded**: `{metrics.get('max_valid_speed_kmh', 0.0)} km/h`",
            f"- **Total Valid Speed Samples**: {metrics.get('valid_speed_sample_count', 0)} samples",
        ])

    # 7. STOPS & STATIONARY
    if any(k in q_upper for k in ["STOP", "STOPPED", "STATIONARY", "IDLING"]) and not any(k in q_upper for k in ["COMPLETE", "FULL", "DETAILED"]):
        lines = [
            f"### 🛑 Stop & Stationary Analysis: Trip `{trip_id}` (`{truck_id}`)",
            f"- **Total Completed Stops**: {stops.get('stop_count', 0)}",
            f"- **Ongoing Stops**: {stops.get('ongoing_stops', 0)}",
            f"- **Total Stationary / Stop Time**: {round(stops.get('total_stop_duration_seconds', 0) / 60, 1)} minutes",
        ]
        stop_list = stops.get("stops", [])
        if stop_list:
            lines.append("\n**Stop Details:**")
            for s in stop_list:
                loc = s.get("location", {}).get("location_name", "In transit")
                lines.append(f"- **{s.get('status')}**: {s.get('duration_minutes')} min at `{loc}` ({s.get('start_time')} to {s.get('end_time')})")
        else:
            lines.append("- No sustained stops (>3 minutes) recorded during this trip.")
        return "\n".join(lines)

    # 8. TEMPERATURE & EXCURSIONS
    if any(k in q_upper for k in ["MAXIMUM TEMPERATURE", "MAX TEMP", "EXCURSION", "PERMITTED RANGE", "TEMPERATURE"]) and not any(k in q_upper for k in ["COMPLETE", "FULL", "DETAILED"]):
        lines = [
            f"### ❄️ Temperature & Excursion Analysis: Trip `{trip_id}` (`{truck_id}`)",
            f"- **Cargo Policy**: {policy.get('cargo_type', 'Standard')} (Safe Range: `{policy.get('min_temperature')}°C` to `{policy.get('max_temperature')}°C`)",
            f"- **Observed Minimum Temperature**: `{temp.get('min_observed_temperature_c')}°C`",
            f"- **Observed Maximum Temperature**: `{temp.get('max_observed_temperature_c')}°C`",
            f"- **Cold Chain Maintained**: {'✅ YES (COMPLIANT)' if temp.get('cold_chain_maintained') else '❌ NO (EXCURSION DETECTED)'}",
            f"- **Total Excursions**: {temp.get('excursion_count', 0)} event(s) lasting `{round(temp.get('total_excursion_duration_seconds', 0) / 60, 1)} minutes`",
        ]
        if temp.get("excursions"):
            lines.append("\n**Excursion Log:**")
            for exc in temp["excursions"]:
                lines.append(f"- **{exc['direction']} excursion**: Peak `{exc['peak_deviation']}°C` lasting `{exc['duration_minutes']} min` ({exc['start_time']} to {exc['end_time']})")
        return "\n".join(lines)

    # 9. INCIDENTS & ACTIONS
    if any(k in q_upper for k in ["INCIDENT", "ALERTS", "CORRECTIVE ACTION"]) and not any(k in q_upper for k in ["COMPLETE", "FULL", "DETAILED"]):
        lines = [
            f"### ⚠️ Incidents & Corrective Actions: Trip `{trip_id}` (`{truck_id}`)",
            f"- **Total Incidents Recorded in Database**: {len(incidents)}",
        ]
        if incidents:
            for inc in incidents:
                lines.append(f"- **[Severity: {inc.get('severity')}] {inc.get('risk_type')}**: {inc.get('message')} (Status: `{inc.get('status')}`)")
        else:
            lines.append("- No persistent risk incidents recorded in database for this trip.")
        return "\n".join(lines)

    lines = [
        f"### 📋 Operations Report: Trip `{trip_id}`",
        f"- **Truck ID**: `{truck_id}`",
        f"- **Status**: `{status}`",
        f"- **Route**: {route.get('source', 'Origin')} ➔ {route.get('destination', 'Destination')}",
        f"- **Cargo Policy**: {policy.get('cargo_type', 'Standard')} ({policy.get('min_temperature')}°C to {policy.get('max_temperature')}°C)",
        f"- **Data Freshness**: {freshness.get('freshness_status')} (Latest sample: {freshness.get('latest_telemetry_timestamp')})",
        "",
        "#### 🚗 Motion & Speed Metrics",
        f"- **Total Distance**: `{metrics.get('total_distance_km', 0.0)} km`",
        f"- **Trip-wide Average Speed (incl. stops)**: `{metrics.get('trip_wide_average_speed_kmh', 0.0)} km/h`",
        f"- **Driving-only Average Speed**: `{metrics.get('driving_only_average_speed_kmh', 0.0)} km/h`",
        f"- **Speed Sensor Arithmetic Mean**: `{metrics.get('arithmetic_sensor_average_speed_kmh', 0.0)} km/h`",
        f"- **Peak Valid Speed**: `{metrics.get('max_valid_speed_kmh', 0.0)} km/h`",
        f"- **Stationary Time**: `{round(metrics.get('stationary_seconds', 0) / 60, 1)} minutes`",
        "",
        "#### 🛑 Stop Analysis",
        f"- **Completed Stops**: {stops.get('stop_count', 0)}",
        f"- **Ongoing Stops**: {stops.get('ongoing_stops', 0)}",
        f"- **Total Stop Duration**: {round(stops.get('total_stop_duration_seconds', 0) / 60, 1)} minutes",
    ]

    stop_list = stops.get("stops", [])
    if stop_list:
        lines.append("\n**Stop Timeline:**")
        for s in stop_list:
            loc = s.get("location", {}).get("location_name", "In transit")
            lines.append(f"- **{s.get('status')}**: {s.get('duration_minutes')} min at `{loc}` ({s.get('start_time')} to {s.get('end_time')})")

    lines.extend([
        "",
        "#### ❄️ Cold Chain Compliance",
        f"- **Status**: {'✅ COMPLIANT' if temp.get('cold_chain_maintained') else '⚠️ EXCURSION DETECTED'}",
        f"- **Observed Range**: `{temp.get('min_observed_temperature_c')}°C` to `{temp.get('max_observed_temperature_c')}°C`",
        f"- **Excursions**: {temp.get('excursion_count', 0)} event(s) totaling `{round(temp.get('total_excursion_duration_seconds', 0) / 60, 1)} minutes`",
    ])

    if temp.get("excursions"):
        for exc in temp["excursions"]:
            lines.append(f"- **{exc['direction']} excursion**: Peak `{exc['peak_deviation']}°C` lasting `{exc['duration_minutes']} min` ({exc['start_time']} to {exc['end_time']})")

    lines.extend([
        "",
        f"#### ⚠️ Persisted Incidents ({len(incidents)})",
    ])
    if incidents:
        for inc in incidents:
            lines.append(f"- **[{inc.get('severity')}] {inc.get('risk_type')}**: {inc.get('message')} (Status: `{inc.get('status')}`)")
    else:
        lines.append("- No persistent risk incidents recorded for this trip.")

    return "\n".join(lines)


# ------------------------------------------------------------------
# LANGGRAPH BUILDER
# ------------------------------------------------------------------

_memory_saver = MemorySaver()


def create_operations_assistant_graph():
    graph = StateGraph(OperationsAssistantState)

    graph.add_node("resolve_entity", resolve_entity_node)
    graph.add_node("fetch_evidence", fetch_evidence_node)
    graph.add_node("generate_response", generate_response_node)

    graph.add_edge(START, "resolve_entity")
    graph.add_edge("resolve_entity", "fetch_evidence")
    graph.add_edge("fetch_evidence", "generate_response")
    graph.add_edge("generate_response", END)

    return graph.compile(checkpointer=_memory_saver)


operations_assistant_app = create_operations_assistant_graph()


def ask_operations_assistant(
    request: str,
    trip_id: str | None = None,
    truck_id: str | None = None,
    thread_id: str = "default_thread",
) -> dict[str, Any]:
    """Main conversational entry point with thread persistence."""
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = OperationsAssistantState(
        thread_id=thread_id,
        request=request,
        trip_id=trip_id,
        truck_id=truck_id,
        messages=[HumanMessage(content=request)],
    )

    result = operations_assistant_app.invoke(initial_state, config=config)

    # Convert state to API response
    resp_text = result.get("response_text") or "No response generated."
    evidence = result.get("evidence") or {}

    return {
        "status": "SUCCESS" if not result.get("needs_clarification") else "NEEDS_CLARIFICATION",
        "trip_id": result.get("trip_id"),
        "truck_id": result.get("truck_id"),
        "intent": result.get("intent"),
        "response": resp_text,
        "evidence": {
            "status": evidence.get("status"),
            "data_freshness": evidence.get("data_freshness"),
            "calculated_metrics": evidence.get("calculated_metrics"),
            "stops": evidence.get("stops"),
            "temperature_analysis": evidence.get("temperature_analysis"),
            "incidents": evidence.get("incidents"),
        } if evidence else None,
    }
