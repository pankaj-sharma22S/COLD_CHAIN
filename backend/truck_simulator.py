import random
import time
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from backend.route import Route
from database.route_repository import get_route
from database.telemetry_repository import (
    create_telemetry_table,
    insert_telemetry,
)
from database.trip_repository import create_trip, complete_trip, get_trip
from database.incident_repository import resolve_trip_incidents
from database.policy_repository import get_policy, get_policy_for_trip
from backend.truck_rules import get_truck_rules_for_trip
from backend.risk_engine import evaluate_truck_risk
from backend.alert_service import record_truck_incidents
from dotenv import load_dotenv
from weather.weather_service import WeatherService

load_dotenv()

SIMULATION_INTERVAL_SECONDS = int(os.getenv("SIMULATION_INTERVAL_SECONDS", "20"))


@dataclass
class TruckState:
    truck_id: str
    trip_id: str
    cargo_policy_id: str

    latitude: float
    longitude: float

    speed_kmh: float

    inside_temperature: float
    outside_temperature: float

    humidity: float

    door_status: str
    door_open_timer_seconds: float

    refrigeration_status: str
    refrigeration_health: float  # 1.0 = nominal, 0.0 = broken

    stopped_timer_seconds: float

    segment_index: int
    segment_progress: float

    total_distance_km: float


class TruckSimulator:

    def __init__(
        self,
        truck_id: str,
        route: Route,
        base_trip_id: str | None = None,
        cargo_policy_id: str | None = None,
        scenario: str = "NORMAL",
        random_seed: int | None = None,
    ):
        self.truck_id = truck_id
        self.route = route
        self.scenario = scenario  # NORMAL, REEFER_FAILURE, DOOR_AJAR, TRAFFIC_DELAY
        if random_seed is not None:
            self._rng = random.Random(random_seed)
        else:
            self._rng = random.Random()

        chosen_trip_id = base_trip_id or os.getenv("DEFAULT_TRIP_ID", f"{truck_id}_{route.route_id}")
        self.trip_id = chosen_trip_id
        if get_trip(chosen_trip_id) is not None:
            suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            self.trip_id = f"{chosen_trip_id}_{suffix}"

        # Resolve cargo policy from database
        if not cargo_policy_id:
            if "002" in truck_id:
                cargo_policy_id = "DEEP_FROZEN"
            elif "003" in truck_id:
                cargo_policy_id = "FRESH_PRODUCE"
            else:
                cargo_policy_id = "PHARMA_VACCINE"
        self.cargo_policy_id = cargo_policy_id

        policy = get_policy(cargo_policy_id)
        self.policy = policy or {
            "id": "PHARMA_VACCINE",
            "cargo_type": "Pharmaceutical Vaccines & Biologics",
            "target_temperature": 5.0,
            "min_temperature": 2.0,
            "max_temperature": 8.0,
        }

        self.trip_started = False
        self.trip_completed = False
        self.step_count = 0
        self.current_time = datetime.now(timezone.utc)

        init_target_temp = float(self.policy.get("target_temperature", 5.0))

        self.state = TruckState(
            truck_id=truck_id,
            trip_id=self.trip_id,
            cargo_policy_id=self.cargo_policy_id,

            latitude=route.source.latitude,
            longitude=route.source.longitude,

            speed_kmh=0.0,

            inside_temperature=init_target_temp,
            outside_temperature=30.0,

            humidity=60.0,

            door_status="CLOSED",
            door_open_timer_seconds=0.0,

            refrigeration_status="ON",
            refrigeration_health=1.0,

            stopped_timer_seconds=0.0,

            segment_index=0,
            segment_progress=0.0,

            total_distance_km=0.0,
        )

        # Precompute milestone road distances
        pts = self.route.road_points
        cum_dists = [0.0] * len(pts)
        for i in range(1, len(pts)):
            cum_dists[i] = cum_dists[i - 1] + self.route.distance_between(pts[i - 1], pts[i])
        self._milestone_distances = []
        milestones = [self.route.source, *self.route.waypoints, self.route.destination]
        for m in milestones:
            best_idx = 0
            min_d = float("inf")
            for idx, pt in enumerate(pts):
                d = self.route.distance_between(pt, m)
                if d < min_d:
                    min_d = d
                    best_idx = idx
            self._milestone_distances.append((cum_dists[best_idx], m))

    # --------------------------------------------------
    # SPEED / VEHICLE DYNAMICS
    # --------------------------------------------------

    def update_speed(self):
        """
        Simulate vehicle dynamics with smooth acceleration, deceleration,
        and stopping at destination or under scenario injection.
        """
        if self.route.is_finished(self.state.segment_index, self.state.segment_progress):
            self.state.speed_kmh = 0.0
            self.state.stopped_timer_seconds += SIMULATION_INTERVAL_SECONDS
            return

        if self.scenario == "TRAFFIC_DELAY" and 5 <= self.step_count <= 25:
            # Stopped or crawling in traffic
            target_speed = 0.0
        else:
            # Cruising speed bounded between 40 and 65 km/h
            target_speed = self._rng.uniform(42.0, 58.0)

        # Smooth acceleration / braking (limited jerk)
        max_delta = 15.0  # max km/h change in one interval
        diff = target_speed - self.state.speed_kmh
        if abs(diff) > max_delta:
            diff = max_delta if diff > 0 else -max_delta

        self.state.speed_kmh = max(0.0, min(80.0, self.state.speed_kmh + diff))

        if self.state.speed_kmh <= 1.0:
            self.state.stopped_timer_seconds += SIMULATION_INTERVAL_SECONDS
        else:
            self.state.stopped_timer_seconds = 0.0

    # --------------------------------------------------
    # AMBIENT WEATHER
    # --------------------------------------------------

    def update_weather(self):
        weather = WeatherService.get_weather(self.state.latitude, self.state.longitude, self.current_time)
        if weather.get("status") != "ERROR":
            self.state.outside_temperature = weather.get("temperature_c", self.state.outside_temperature)
            self.state.humidity = weather.get("humidity_percent", self.state.humidity)

    # --------------------------------------------------
    # DOOR STATE MACHINE
    # --------------------------------------------------

    def update_door(self):
        """
        Persistent door state machine with explicit opening and closing cycles.
        """
        if self.scenario == "DOOR_AJAR" and self.step_count >= 4:
            self.state.door_status = "OPEN"
            self.state.door_open_timer_seconds += SIMULATION_INTERVAL_SECONDS
            return

        if self.state.door_status == "OPEN":
            self.state.door_open_timer_seconds += SIMULATION_INTERVAL_SECONDS
            # Door closes after brief inspection (~40-60s)
            if self.state.door_open_timer_seconds >= 60.0 or self._rng.random() < 0.35:
                self.state.door_status = "CLOSED"
                self.state.door_open_timer_seconds = 0.0
        else:
            self.state.door_open_timer_seconds = 0.0
            # Low probability of door opening during normal transit (< 2%)
            if self._rng.random() < 0.02 and self.state.speed_kmh < 20.0:
                self.state.door_status = "OPEN"

    # --------------------------------------------------
    # REFRIGERATION
    # --------------------------------------------------

    def update_refrigeration(self):
        """
        Refrigeration status responding to scenario or failures.
        """
        reefer_fail_env = int(os.getenv("SIMULATOR_REFRIGERATION_FAILURE_AFTER_STEPS", "-1"))
        if (
            (reefer_fail_env >= 0 and self.step_count >= reefer_fail_env)
            or (self.scenario == "REEFER_FAILURE" and self.step_count >= 3)
        ):
            self.state.refrigeration_status = "OFF"
            self.state.refrigeration_health = 0.0
        else:
            self.state.refrigeration_status = "ON"
            self.state.refrigeration_health = 1.0

    # --------------------------------------------------
    # PHYSICAL THERMAL MODEL
    # --------------------------------------------------

    def update_inside_temperature(self):
        """
        Continuous physical heat-exchange model:
        dT/dt = k_reefer * (T_target - T) + k_ambient * (T_outside - T) + k_door * (T_outside - T)
        """
        target_temp = float(self.policy.get("target_temperature", 5.0))
        t_inside = self.state.inside_temperature
        t_outside = self.state.outside_temperature

        # Physical heat transfer coefficients per simulation interval (20s)
        # Reefer active temperature maintenance pull-down rate
        k_reefer = 0.35 if self.state.refrigeration_status == "ON" else 0.0
        # Passive insulated container heat transmission
        k_ambient = 0.02
        # Door open massive convective transfer
        k_door = 0.25 if self.state.door_status == "OPEN" else 0.0

        # Differential heat exchange
        delta_cooling = k_reefer * (target_temp - t_inside)
        delta_ambient_leakage = k_ambient * (t_outside - t_inside)
        delta_door_convection = k_door * (t_outside - t_inside)

        # Micro sensor jitter (noise)
        noise = self._rng.uniform(-0.03, 0.03)

        self.state.inside_temperature = round(
            t_inside + delta_cooling + delta_ambient_leakage + delta_door_convection + noise,
            2,
        )

    # --------------------------------------------------
    # POSITION ALONG ROUTE
    # --------------------------------------------------

    def update_position(self):
        """
        Advance position continuously along route road geometry.
        """
        if self.route.is_finished(self.state.segment_index, self.state.segment_progress):
            self.state.speed_kmh = 0.0
            return

        segment_distance = self.route.segment_distance_km(self.state.segment_index)
        if segment_distance <= 0:
            return

        distance_this_step = self.state.speed_kmh * SIMULATION_INTERVAL_SECONDS / 3600.0
        progress_change = distance_this_step / segment_distance
        self.state.segment_progress += progress_change

        while (
            self.state.segment_progress >= 1.0
            and self.state.segment_index < self.route.segment_count - 1
        ):
            self.state.segment_progress -= 1.0
            self.state.segment_index += 1

        if (
            self.state.segment_index == self.route.segment_count - 1
            and self.state.segment_progress >= 1.0
        ):
            self.state.segment_progress = 1.0
            self.state.speed_kmh = 0.0

        current_position = self.route.current_point(
            self.state.segment_index,
            self.state.segment_progress,
        )

        self.state.latitude = current_position.latitude
        self.state.longitude = current_position.longitude

        # Recalculate total distance
        self.state.total_distance_km = 0.0
        for index in range(self.state.segment_index):
            self.state.total_distance_km += self.route.segment_distance_km(index)

        if self.state.segment_index < self.route.segment_count:
            self.state.total_distance_km += (
                self.route.segment_distance_km(self.state.segment_index)
                * self.state.segment_progress
            )

    # --------------------------------------------------
    # TELEMETRY GENERATION
    # --------------------------------------------------

    def generate_telemetry(self) -> dict:
        current_station = self.route.source
        next_station = self.route.destination
        for dist_km, m in getattr(self, "_milestone_distances", []):
            if dist_km <= self.state.total_distance_km:
                current_station = m
            elif dist_km > self.state.total_distance_km:
                next_station = m
                break

        return {
            "truck_id": self.state.truck_id,
            "trip_id": self.trip_id,
            "cargo_policy_id": self.cargo_policy_id,
            "cargo_type": self.policy.get("cargo_type"),

            "latitude": self.state.latitude,
            "longitude": self.state.longitude,

            "speed_kmh": round(self.state.speed_kmh, 1),
            "stopped_duration_seconds": self.state.stopped_timer_seconds,

            "inside_temperature": self.state.inside_temperature,
            "outside_temperature": self.state.outside_temperature,
            "humidity": self.state.humidity,

            "door_status": self.state.door_status,
            "door_open_duration_seconds": self.state.door_open_timer_seconds,

            "refrigeration_status": self.state.refrigeration_status,

            "current_point": {
                "name": current_station.name or self.route.source.name,
                "latitude": self.state.latitude,
                "longitude": self.state.longitude,
            },

            "next_point": {
                "name": next_station.name or self.route.destination.name,
                "latitude": next_station.latitude,
                "longitude": next_station.longitude,
            },

            "segment_index": self.state.segment_index,
            "segment_progress": self.state.segment_progress,
            "total_distance_km": round(self.state.total_distance_km, 2),
            "route_id": self.route.route_id,
            "source": self.route.source.name,
            "destination": self.route.destination.name,
        }

    # --------------------------------------------------
    # INGESTION PIPELINE: STEP & PERSIST
    # --------------------------------------------------

    def step(self) -> dict:
        """
        Advance one simulation step, generate telemetry, evaluate risk,
        persist to DB, and upsert persistent incidents.
        """
        self.step_count += 1
        self.current_time += timedelta(seconds=SIMULATION_INTERVAL_SECONDS)

        self.update_speed()
        self.update_weather()
        self.update_door()
        self.update_refrigeration()
        self.update_inside_temperature()
        self.update_position()

        telemetry = self.generate_telemetry()
        return telemetry

    def ingest_telemetry_pipeline(self, telemetry: dict) -> None:
        """
        Authoritative telemetry ingestion:
        1. Persist telemetry to database.
        2. Evaluate deterministic risk against cargo policy.
        3. Persist / resolve active incidents in MySQL.
        """
        # 1. Insert telemetry record
        insert_telemetry(telemetry)

        # 2. Evaluate risk
        rules = get_truck_rules_for_trip(telemetry["truck_id"], trip_id=telemetry["trip_id"])
        risk = evaluate_truck_risk(telemetry, rules=rules)
        telemetry_with_risk = {**telemetry, "risk": risk}

        # 3. Update persistent incidents in DB
        record_truck_incidents(telemetry_with_risk)

    def run(self, stop_event=None):
        print(f"Starting simulator for truck '{self.truck_id}' [Policy: {self.cargo_policy_id}]")
        print(f"Route: {self.route.source.name} -> {self.route.destination.name}")

        create_trip(
            self.trip_id,
            self.truck_id,
            self.route.route_id,
            cargo_policy_id=self.cargo_policy_id,
            cargo_type=self.policy.get("cargo_type"),
        )
        self.trip_started = True

        while not self.trip_completed and not (stop_event and stop_event.is_set()):
            telemetry = self.step()
            self.ingest_telemetry_pipeline(telemetry)

            if self.route.is_finished(
                self.state.segment_index, self.state.segment_progress
            ):
                complete_trip(self.trip_id)
                try:
                    resolve_trip_incidents(self.trip_id)
                except Exception as e:
                    print(f"Warning: Failed to resolve trip incidents on completion: {e}")
                self.trip_completed = True
                print(f"Trip '{self.trip_id}' completed.")
                break

            if stop_event:
                stop_event.wait(SIMULATION_INTERVAL_SECONDS)
            else:
                time.sleep(SIMULATION_INTERVAL_SECONDS)
