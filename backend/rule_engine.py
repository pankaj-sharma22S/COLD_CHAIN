"""Backward-compatible facade for the authoritative root risk engine."""

from backend.truck_rules import get_truck_rules
from backend.risk_engine import evaluate_truck_risk


class RuleEngine:
    """Compatibility facade; all rule evaluation lives in ``risk_engine``."""

    def __init__(self, truck_rules):
        self.rules = truck_rules

    def evaluate(self, telemetry: dict) -> dict:
        return evaluate_truck_risk(telemetry, self.rules)


def evaluate_truck(truck_id: str, telemetry: dict) -> dict:
    return evaluate_truck_risk(telemetry, get_truck_rules(truck_id))
