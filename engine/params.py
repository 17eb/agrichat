"""Reviewer decisions shared by the engine and the offline pipeline."""

# PLACEHOLDER: pending reviewer; represent Nov 1-30 with sowing on Nov 1.
SOWING_WINDOW = ((11, 1), (11, 30))
# PLACEHOLDER: pending reviewer; assumed 100 mm, no value suggested in the spec
ROOT_ZONE_WATER_CAPACITY_MM = 100.0
# PLACEHOLDER: pending reviewer.
ADEQUACY_THRESHOLD = 0.8
# PLACEHOLDER: pending reviewer; midpoint values suggested by the spec.
KC_END = {"rice": 0.75, "mungbean": 0.475, "soybean": 0.50}
# PLACEHOLDER: pending reviewer; provisional zero soaking/seepage allowance.
RICE_EXTRA_ALLOWANCE_MM = 0.0
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

# PLACEHOLDER: pending reviewer; flowering is the scaled mid stage in the pipeline.
