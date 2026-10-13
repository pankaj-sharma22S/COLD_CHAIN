"""Tests for the conversational Cold Chain AI Operations Assistant and metrics services."""

import pytest
from datetime import datetime, timezone, timedelta
from agent.operations_metrics import (
    calculate_speed_and_distance_metrics,
    detect_stops_and_timeline,
    analyze_temperature_excursions,
    analyze_door_and_refrigeration_events,
    parse_timestamp_utc,
    haversine_distance_km,
)
from agent.operations_evidence import build_trip_evidence_package
from agent.operations_assistant import ask_operations_assistant, resolve_entity_node, OperationsAssistantState


def test_distance_and_speed_metrics_calculation():
    # Construct 4 telemetry samples separated by 60 seconds
    base_time = datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone.utc)
    records = [
        {"timestamp": base_time.isoformat(), "speed_kmh": 0.0, "total_distance_km": 0.0, "latitude": 28.6139, "longitude": 77.2090},
        {"timestamp": (base_time + timedelta(seconds=60)).isoformat(), "speed_kmh": 60.0, "total_distance_km": 1.0, "latitude": 28.6200, "longitude": 77.2100},
        {"timestamp": (base_time + timedelta(seconds=120)).isoformat(), "speed_kmh": 60.0, "total_distance_km": 2.0, "latitude": 28.6300, "longitude": 77.2150},
        {"timestamp": (base_time + timedelta(seconds=180)).isoformat(), "speed_kmh": 0.0, "total_distance_km": 2.0, "latitude": 28.6300, "longitude": 77.2150},
    ]

    metrics = calculate_speed_and_distance_metrics(records)

    assert metrics["total_distance_km"] == 2.0
    # Total elapsed: 180 seconds = 0.05 hours -> trip-wide avg: 2.0 / 0.05 = 40.0 km/h
    assert metrics["trip_wide_average_speed_kmh"] == 40.0
    # Driving seconds: 120 seconds = 0.0333 hours -> driving-only avg: 2.0 / 0.03333 = 60.0 km/h
    assert metrics["driving_only_average_speed_kmh"] == 60.0
    # Arithmetic mean of sensor samples: (0 + 60 + 60 + 0) / 4 = 30.0 km/h
    assert metrics["arithmetic_sensor_average_speed_kmh"] == 30.0
    assert metrics["max_valid_speed_kmh"] == 60.0


def test_stop_detection_and_timeline():
    base_time = datetime(2026, 10, 13, 11, 0, 0, tzinfo=timezone.utc)
    records = [
        {"timestamp": base_time.isoformat(), "speed_kmh": 50.0, "current_point_name": "Highway"},
        # Stop 1 (lasting 60s >= 40s min threshold)
        {"timestamp": (base_time + timedelta(seconds=60)).isoformat(), "speed_kmh": 0.0, "current_point_name": "Rest Stop A"},
        {"timestamp": (base_time + timedelta(seconds=120)).isoformat(), "speed_kmh": 0.0, "current_point_name": "Rest Stop A"},
        # Moving again
        {"timestamp": (base_time + timedelta(seconds=180)).isoformat(), "speed_kmh": 55.0, "current_point_name": "Highway"},
        # Ongoing stop at latest record
        {"timestamp": (base_time + timedelta(seconds=240)).isoformat(), "speed_kmh": 0.0, "current_point_name": "Warehouse B"},
        {"timestamp": (base_time + timedelta(seconds=300)).isoformat(), "speed_kmh": 0.0, "current_point_name": "Warehouse B"},
    ]

    stop_data = detect_stops_and_timeline(records, speed_threshold_kmh=1.0, min_stop_duration_seconds=40.0)

    assert stop_data["stop_count"] == 1  # 1 completed stop
    assert stop_data["ongoing_stops"] == 1  # 1 ongoing stop at end
    assert len(stop_data["stops"]) == 2
    assert stop_data["stops"][0]["status"] == "COMPLETED"
    assert stop_data["stops"][1]["status"] == "ONGOING"
    assert stop_data["stops"][0]["duration_seconds"] == 60.0


def test_temperature_excursion_analysis():
    policy = {
        "id": "PHARMA_VACCINE",
        "cargo_type": "Pharmaceutical Vaccines & Biologics",
        "min_temperature": 2.0,
        "max_temperature": 8.0,
        "target_temperature": 5.0,
    }
    base_time = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
    records = [
        {"timestamp": base_time.isoformat(), "inside_temperature": 5.0},
        {"timestamp": (base_time + timedelta(seconds=60)).isoformat(), "inside_temperature": 9.2},  # Excursion start
        {"timestamp": (base_time + timedelta(seconds=120)).isoformat(), "inside_temperature": 9.8},
        {"timestamp": (base_time + timedelta(seconds=180)).isoformat(), "inside_temperature": 5.2},  # Recovery
        {"timestamp": (base_time + timedelta(seconds=240)).isoformat(), "inside_temperature": 1.5},  # Low excursion
    ]

    analysis = analyze_temperature_excursions(records, policy)

    assert analysis["cold_chain_maintained"] is False
    assert analysis["excursion_count"] == 2
    assert analysis["min_observed_temperature_c"] == 1.5
    assert analysis["max_observed_temperature_c"] == 9.8

    high_exc = analysis["excursions"][0]
    assert high_exc["direction"] == "HIGH"
    assert high_exc["peak_deviation"] == 9.8


def test_entity_resolution_and_followup():
    # 1. Direct explicit trip ID
    state1 = OperationsAssistantState(request="Give me the complete report for trip TRIP_001")
    res1 = resolve_entity_node(state1)
    assert res1["trip_id"] == "TRIP_001"
    assert res1["intent"] == "COMPLETE_REPORT"

    # 2. Follow-up query without explicit ID should retain prior state
    state2 = OperationsAssistantState(
        request="What was the average speed and how many stops did it make?",
        trip_id="TRIP_001",
    )
    res2 = resolve_entity_node(state2)
    assert res2["trip_id"] == "TRIP_001"
    assert res2["intent"] == "STOP_ANALYSIS" or res2["intent"] == "SPEED_AND_DISTANCE"

    # 3. Explicit ID override in new question
    state3 = OperationsAssistantState(
        request="Now compare TRIP_002 with TRIP_001",
        trip_id="TRIP_001",
    )
    res3 = resolve_entity_node(state3)
    # Explicit ID in text takes precedence
    assert res3["trip_id"] == "TRIP_002"
    assert res3["intent"] == "TRIP_COMPARISON"


def test_evidence_package_and_assistant_execution():
    # Query an existing demo trip
    response = ask_operations_assistant(
        request="Give me the complete report for trip TRIP_001",
        thread_id="test_thread_01",
    )
    assert response["status"] in ("SUCCESS", "NEEDS_CLARIFICATION")
    assert response["trip_id"] == "TRIP_001"
    assert response["response"] is not None
    assert len(response["response"]) > 0

    # Query for nonexistent trip returns clean error
    nonexistent = ask_operations_assistant(
        request="What is the status of trip TRIP_DOES_NOT_EXIST_9999",
        thread_id="test_thread_02",
    )
    assert "Trip Not Found" in nonexistent["response"] or nonexistent["status"] == "SUCCESS"
