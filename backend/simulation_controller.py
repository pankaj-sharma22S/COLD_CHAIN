"""Process-local controller for the truck simulator supporting multiple simultaneous trucks."""

import os
import threading
from datetime import datetime, timezone

from database.route_repository import get_route
from database.trip_repository import cancel_trip
from database.incident_repository import resolve_all_active_incidents, resolve_trip_incidents
from backend.truck_simulator import TruckSimulator

DEFAULT_FLEET = [
    {"truck_id": "T001", "route_id": "route_001", "cargo_policy_id": "PHARMA_VACCINE", "scenario": "NORMAL"},
    {"truck_id": "TRUCK_002", "route_id": "route_002", "cargo_policy_id": "DEEP_FROZEN", "scenario": "NORMAL"},
    {"truck_id": "TRUCK_003", "route_id": "route_003", "cargo_policy_id": "FRESH_PRODUCE", "scenario": "NORMAL"},
]


class SimulationController:
    def __init__(self):
        self._lock = threading.RLock()
        self._threads: list[threading.Thread] = []
        self._stop_event: threading.Event | None = None
        self._simulators: list[TruckSimulator] = []
        self._started_at: datetime | None = None
        self._last_error: str | None = None

    def status(self) -> dict:
        with self._lock:
            running = bool(self._threads and any(t.is_alive() for t in self._threads))
            first_sim = self._simulators[0] if self._simulators else None
            return {
                "status": "RUNNING" if running else "STOPPED",
                "active_truck_count": len(self._simulators) if running else 0,
                "trucks": [
                    {
                        "truck_id": s.truck_id,
                        "trip_id": s.trip_id,
                        "route_id": s.route.route_id,
                        "cargo_policy_id": s.cargo_policy_id,
                    }
                    for s in self._simulators
                ] if running else [],
                "truck_id": first_sim.truck_id if first_sim else None,
                "trip_id": first_sim.trip_id if first_sim else None,
                "route_id": first_sim.route.route_id if first_sim else None,
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "last_error": self._last_error,
            }

    def start(
        self,
        fleet_configs: list[dict] | None = None,
        truck_id: str | None = None,
        route_id: str | None = None,
        cargo_policy_id: str | None = None,
    ) -> dict:
        with self._lock:
            if self._threads and any(t.is_alive() for t in self._threads):
                return self.status()

            if truck_id and route_id:
                configs = [{"truck_id": truck_id, "route_id": route_id, "cargo_policy_id": cargo_policy_id or "PHARMA_VACCINE", "scenario": "NORMAL"}]
            elif fleet_configs:
                configs = fleet_configs
            else:
                configs = DEFAULT_FLEET

            # Clean up any lingering active incidents from previous runs so new run starts clean
            try:
                resolve_all_active_incidents()
            except Exception as e:
                print(f"Notice: Failed to resolve previous incidents on sim start: {e}")

            self._stop_event = threading.Event()
            self._last_error = None
            self._simulators = []
            self._threads = []
            self._started_at = datetime.now(timezone.utc)
            timestamp_str = self._started_at.strftime("%Y%m%d%H%M%S")

            for cfg in configs:
                t_id = cfg["truck_id"]
                r_id = cfg["route_id"]
                c_policy = cfg.get("cargo_policy_id")
                scenario = cfg.get("scenario", "NORMAL")

                route = get_route(r_id)
                if route is None:
                    print(f"Warning: Route '{r_id}' was not found for truck '{t_id}'")
                    continue

                trip_id = f"TRIP_{t_id}_{timestamp_str}"
                sim = TruckSimulator(
                    t_id,
                    route,
                    base_trip_id=trip_id,
                    cargo_policy_id=c_policy,
                    scenario=scenario,
                )
                self._simulators.append(sim)

                t = threading.Thread(
                    target=self._run_sim,
                    args=(sim, self._stop_event),
                    name=f"sim-{t_id}",
                    daemon=True,
                )
                self._threads.append(t)

            for t in self._threads:
                t.start()

            return self.status()

    def _run_sim(self, sim: TruckSimulator, stop_event: threading.Event):
        try:
            sim.run(stop_event)
        except Exception as error:
            with self._lock:
                self._last_error = str(error)
                print(f"Simulator exception for truck '{sim.truck_id}': {error}")

    def stop(self) -> dict:
        with self._lock:
            if self._stop_event:
                self._stop_event.set()
            threads = list(self._threads)

        for t in threads:
            t.join(timeout=4)

        with self._lock:
            for sim in self._simulators:
                if not sim.trip_completed:
                    try:
                        cancel_trip(sim.trip_id)
                        resolve_trip_incidents(sim.trip_id)
                    except Exception as err:
                        print(f"Error cancelling trip '{sim.trip_id}': {err}")
            # Ensure all remaining active incidents are closed upon stopping
            try:
                resolve_all_active_incidents()
            except Exception as err:
                print(f"Error resolving incidents on stop: {err}")
            self._simulators = []
            self._threads = []

        return self.status()


simulation_controller = SimulationController()
