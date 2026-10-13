"""Database-backed truck rules and temperature limits."""

from dataclasses import dataclass
from database.policy_repository import get_policy, get_policy_for_trip

DEFAULT_MIN_TEMPERATURE: float = 2.0
DEFAULT_MAX_TEMPERATURE: float = 8.0
DEFAULT_TARGET_TEMPERATURE: float = 5.0


@dataclass
class TruckRules:
    """
    Rules configured for a truck / trip, resolved from database policies.
    """

    truck_id: str
    cargo_policy_id: str = "PHARMA_VACCINE"
    cargo_type: str = "Pharmaceutical Vaccines & Biologics"

    min_temperature: float = DEFAULT_MIN_TEMPERATURE
    max_temperature: float = DEFAULT_MAX_TEMPERATURE
    target_temperature: float = DEFAULT_TARGET_TEMPERATURE
    warning_margin: float = 1.0

    door_open_allowed_seconds: int = 60
    stopped_allowed_seconds: int = 300
    data_loss_allowed_seconds: int = 120

    def __post_init__(self):
        if self.min_temperature is None:
            self.min_temperature = DEFAULT_MIN_TEMPERATURE
        if self.max_temperature is None:
            self.max_temperature = DEFAULT_MAX_TEMPERATURE

    @property
    def min_temp(self) -> float:
        return self.min_temperature

    @property
    def max_temp(self) -> float:
        return self.max_temperature


class TemperatureLimits(dict):
    """Container for truck temperature limits supporting both key and attribute access."""

    def __init__(self, min_temp: float, max_temp: float, target_temp: float = DEFAULT_TARGET_TEMPERATURE):
        min_f = float(min_temp)
        max_f = float(max_temp)
        tgt_f = float(target_temp)
        super().__init__(min_temp=min_f, max_temp=max_f, target_temp=tgt_f)

    @property
    def min_temp(self) -> float:
        return self["min_temp"]

    @property
    def max_temp(self) -> float:
        return self["max_temp"]

    @property
    def target_temp(self) -> float:
        return self.get("target_temp", DEFAULT_TARGET_TEMPERATURE)


def get_truck_rules_for_trip(truck_id: str, trip_id: str | None = None) -> TruckRules:
    """
    Load rules from database cargo_temperature_policies for this trip/truck.
    """
    policy = None
    if trip_id:
        try:
            policy = get_policy_for_trip(trip_id)
        except Exception:
            pass

    if not policy:
        # Check if truck has a default policy mapping
        # E.g. TRUCK_002 defaults to DEEP_FROZEN if not in an active trip
        if "002" in str(truck_id):
            policy = get_policy("DEEP_FROZEN")
        elif "003" in str(truck_id):
            policy = get_policy("FRESH_PRODUCE")
        else:
            policy = get_policy("PHARMA_VACCINE")

    if policy:
        return TruckRules(
            truck_id=truck_id,
            cargo_policy_id=policy.get("id", "PHARMA_VACCINE"),
            cargo_type=policy.get("cargo_type", "Pharmaceutical Vaccines & Biologics"),
            min_temperature=float(policy.get("min_temperature", DEFAULT_MIN_TEMPERATURE)),
            max_temperature=float(policy.get("max_temperature", DEFAULT_MAX_TEMPERATURE)),
            target_temperature=float(policy.get("target_temperature", DEFAULT_TARGET_TEMPERATURE)),
            warning_margin=float(policy.get("warning_margin", 1.0)),
            door_open_allowed_seconds=int(policy.get("door_open_allowed_seconds", 60)),
            stopped_allowed_seconds=int(policy.get("stopped_allowed_seconds", 300)),
            data_loss_allowed_seconds=int(policy.get("data_loss_allowed_seconds", 120)),
        )

    return TruckRules(
        truck_id=truck_id,
        min_temperature=DEFAULT_MIN_TEMPERATURE,
        max_temperature=DEFAULT_MAX_TEMPERATURE,
        target_temperature=DEFAULT_TARGET_TEMPERATURE,
        door_open_allowed_seconds=60,
        stopped_allowed_seconds=300,
        data_loss_allowed_seconds=120,
    )


def get_truck_rules(truck_id: str) -> TruckRules:
    """
    Get rules configured for a specific truck.
    Resolves dynamically from database policies.
    """
    return get_truck_rules_for_trip(truck_id)


def get_temperature_limits(truck_id: str | None = None, trip_id: str | None = None) -> TemperatureLimits:
    """
    Returns the database-configured min_temp, max_temp, and target_temp.
    """
    if not truck_id and not trip_id:
        return TemperatureLimits(
            min_temp=DEFAULT_MIN_TEMPERATURE,
            max_temp=DEFAULT_MAX_TEMPERATURE,
            target_temp=DEFAULT_TARGET_TEMPERATURE,
        )

    rules = get_truck_rules_for_trip(truck_id or "UNKNOWN", trip_id=trip_id)
    return TemperatureLimits(
        min_temp=float(rules.min_temp),
        max_temp=float(rules.max_temp),
        target_temp=float(rules.target_temperature),
    )
