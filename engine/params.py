"""Reviewer decisions shared by the engine and the offline pipeline."""

# PLACEHOLDER: pending reviewer; no sowing dates are suggested in the spec.
SOWING_WINDOW: tuple[tuple[int, int], tuple[int, int]] | None = None
# PLACEHOLDER: pending reviewer; no capacity is suggested in the spec.
ROOT_ZONE_WATER_CAPACITY_MM: float | None = None
# PLACEHOLDER: pending reviewer.
ADEQUACY_THRESHOLD = 0.8
# PLACEHOLDER: pending reviewer; midpoint values suggested by the spec.
KC_END = {"rice": 0.75, "mungbean": 0.475, "soybean": 0.50}
# PLACEHOLDER: pending reviewer; no allowance is suggested in the spec.
RICE_EXTRA_ALLOWANCE_MM: float | None = None
# PLACEHOLDER: pending reviewer.
SCORING_WEIGHTS = {
    "water_reliability": 50,
    "rotation_benefit": 20,
    "timing_risk": 20,
    "farmer_priority": 10,
}
# PLACEHOLDER: pending reviewer.
HEAT_THRESHOLD_C = 35.0
# PLACEHOLDER: pending reviewer.
HARVEST_RAIN_THRESHOLD_MM = 50.0
