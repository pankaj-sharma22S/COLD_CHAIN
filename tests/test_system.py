"""Unit and integration tests for cold-chain policies, simulation, risk evaluation, and incidents."""

import pytest
from datetime import datetime, timezone, timedelta
from backend.truck_rules import get_truck_rules_for_trip, TruckRules, get_temperature_limits
from backend.risk_engine import evaluate_truck_risk, evaluate_fleet_risk
from backend.truck_simulator import TruckSimulator
from database.route_repository import get_route
from database.policy_repository import get_policy, list_policies
from database.incident_repository import upsert_incident, resolve_missing_incidents, list_incidents, acknowledge_incident


def test_cargo_policies_loaded():
    policies = list_policies()
    assert len(policies) >= 3
    policy_ids = [p["id"] for p in policies]
    assert "PHARMA_VACCINE" in policy_ids
    assert "DEEP_FROZEN" in policy_ids
    assert "FRESH_PRODUCE" in policy_ids


def test_policy_resolution_by_trip_and_truck():
    # Vaccine policy (2.0 to 8.0)
    vaccine_rules = get_truck_rules_for_trip("T001", trip_id=None)
    assert vaccine_rules.min_temperature == 2.0
    assert vaccine_rules.max_temperature == 8.0
    assert vaccine_rules.target_temperature == 5.0

    # Frozen policy (-25.0 to -18.0)
    frozen_rules = get_truck_rules_for_trip("TRUCK_002", trip_id=None)
    assert frozen_rules.min_temperature == -25.0
    assert frozen_rules.max_temperature == -18.0
    assert frozen_rules.target_temperature == -20.0

    # Limits accessor
    limits = get_temperature_limits("TRUCK_002")
    assert limits.min_temp == -25.0
    assert limits.max_temp == -18.0


def test_risk_evaluation_temperature_excursion():
    rules = TruckRules(
        truck_id="TEST_01",
        cargo_policy_id="PHARMA_VACCINE",
        cargo_type="Pharmaceutical Vaccines",
        min_temperature=2.0,
        max_temperature=8.0,
        door_open_allowed_seconds=60,
        stopped_allowed_seconds=300,
        data_loss_allowed_seconds=120,
    )

    # 1. Normal state inside safe band
    normal_data = {
        "truck_id": "TEST_01",
        "inside_temperature": 5.0,
        "door_status": "CLOSED",
        "refrigeration_status": "ON",
        "speed_kmh": 50.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    res_normal = evaluate_truck_risk(normal_data, rules=rules)
    assert res_normal["status"] == "NORMAL"
    assert len(res_normal["reasons"]) == 0

    # 2. High temperature excursion (9.5°C > 8.0°C)
    high_temp_data = {**normal_data, "inside_temperature": 9.5}
    res_high = evaluate_truck_risk(high_temp_data, rules=rules)
    assert res_high["status"] == "RISKY"
    reasons = [r["type"] for r in res_high["reasons"]]
    assert "TEMPERATURE_HIGH" in reasons

    # 3. Sub-cooling low temperature excursion (0.5°C < 2.0°C)
    low_temp_data = {**normal_data, "inside_temperature": 0.5}
    res_low = evaluate_truck_risk(low_temp_data, rules=rules)
    assert res_low["status"] == "RISKY"
    reasons = [r["type"] for r in res_low["reasons"]]
    assert "TEMPERATURE_LOW" in reasons


def test_risk_evaluation_door_and_refrigeration():
    rules = TruckRules(
        truck_id="TEST_02",
        cargo_policy_id="PHARMA_VACCINE",
        min_temperature=2.0,
        max_temperature=8.0,
        door_open_allowed_seconds=60,
        stopped_allowed_seconds=300,
        data_loss_allowed_seconds=120,
    )

    # Reefer OFF is critical risk
    reefer_off_data = {
        "truck_id": "TEST_02",
        "inside_temperature": 5.0,
        "door_status": "CLOSED",
        "refrigeration_status": "OFF",
        "speed_kmh": 40.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    res_reefer = evaluate_truck_risk(reefer_off_data, rules=rules)
    assert res_reefer["status"] == "RISKY"
    assert any(r["type"] == "REFRIGERATION_OFF" for r in res_reefer["reasons"])

    # Door open beyond allowed threshold
    door_open_data = {
        "truck_id": "TEST_02",
        "inside_temperature": 5.0,
        "door_status": "OPEN",
        "door_open_duration_seconds": 90.0,  # > 60s
        "refrigeration_status": "ON",
        "speed_kmh": 0.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    res_door = evaluate_truck_risk(door_open_data, rules=rules)
    assert res_door["status"] == "RISKY"
    assert any(r["type"] == "DOOR_OPEN" for r in res_door["reasons"])


def test_staleness_timezone_normalization():
    rules = TruckRules(
        truck_id="TEST_03",
        data_loss_allowed_seconds=120,
    )
    now_utc = datetime.now(timezone.utc)

    # 1. Fresh telemetry (10 seconds ago) -> NORMAL
    fresh_data = {
        "truck_id": "TEST_03",
        "inside_temperature": 5.0,
        "refrigeration_status": "ON",
        "door_status": "CLOSED",
        "timestamp": (now_utc - timedelta(seconds=10)).isoformat(),
    }
    assert evaluate_truck_risk(fresh_data, rules=rules)["status"] == "NORMAL"

    # 2. Stale telemetry (300 seconds ago) -> RISKY
    stale_data = {
        "truck_id": "TEST_03",
        "inside_temperature": 5.0,
        "refrigeration_status": "ON",
        "door_status": "CLOSED",
        "timestamp": (now_utc - timedelta(seconds=300)).isoformat(),
    }
    res_stale = evaluate_truck_risk(stale_data, rules=rules)
    assert res_stale["status"] == "RISKY"
    assert any(r["type"] == "TELEMETRY_STALE" for r in res_stale["reasons"])


def test_persistent_incident_lifecycle():
    trip_id = "TRIP_TEST_LIFECYCLE"
    truck_id = "TRUCK_TEST_01"

    # 1. Upsert incident
    inc = upsert_incident(
        trip_id=trip_id,
        truck_id=truck_id,
        risk_type="TEMPERATURE_HIGH",
        severity="HIGH",
        message="Temperature 9.2°C exceeds 8.0°C limit",
        current_value=9.2,
        threshold_violated="[2.0, 8.0]",
    )
    assert inc["id"] > 0
    assert inc["status"] == "ACTIVE"

    # 2. Deduplication check: repeated detection updates last_observed_at without creating new ID
    inc2 = upsert_incident(
        trip_id=trip_id,
        truck_id=truck_id,
        risk_type="TEMPERATURE_HIGH",
        severity="HIGH",
        message="Temperature 9.4°C exceeds 8.0°C limit",
        current_value=9.4,
        threshold_violated="[2.0, 8.0]",
    )
    assert inc2["id"] == inc["id"]
    assert inc2["current_value"] == 9.4

    # 3. Acknowledge incident
    ack = acknowledge_incident(inc["id"])
    assert ack is not None
    assert ack["status"] == "ACKNOWLEDGED"

    # 4. Resolve incident when condition clears
    resolved = resolve_missing_incidents(
        trip_id=trip_id,
        truck_id=truck_id,
        active_risk_types=set(),  # condition cleared
    )
    assert inc["id"] in resolved


def test_stateful_simulator_vehicle_and_thermal_dynamics():
    route = get_route("route_001")
    assert route is not None

    sim = TruckSimulator(
        truck_id="T001",
        route=route,
        base_trip_id="TRIP_TEST_SIM",
        cargo_policy_id="PHARMA_VACCINE",
        random_seed=42,
    )

    assert sim.state.inside_temperature == 5.0
    assert sim.state.speed_kmh == 0.0

    # Step forward 3 times (60 simulation seconds)
    t1 = sim.step()
    assert t1["speed_kmh"] > 0.0
    assert t1["total_distance_km"] >= 0.0

    t2 = sim.step()
    t3 = sim.step()
    # Thermal temperature should remain close to target with reefer ON and door CLOSED
    assert 4.0 <= t3["inside_temperature"] <= 6.0
    # Progress should advance
    assert sim.state.total_distance_km > 0.0
