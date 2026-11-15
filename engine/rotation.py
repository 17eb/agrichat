"""Pure ranking of the pilot's rainfed crop candidates.

Callers supply the sowing date and indicators for the current window. No clock,
configuration, database or weather access occurs while making a recommendation.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from engine import params


@dataclass(frozen=True)
class Profile:
    barangay_code: str
    last_crop: str | None
    water_source: str
    priority: str | None
    sowing_date: date


@dataclass(frozen=True)
class Crop:
    name: str
    is_legume: bool
    seasonal_water_demand: float
    income_flag: float | None = None


@dataclass(frozen=True)
class Indicator:
    n_years: int
    n_adequate: int
    n_elnino: int
    n_adequate_elnino: int
    heat_freq: float
    harvest_rain_freq: float
    barangay_code: str
    sow_window: str


@dataclass(frozen=True)
class ScoredCrop:
    name: str
    total: float
    water_reliability: float
    rotation_benefit: float
    timing_risk: float
    farmer_priority: float
    n_adequate: int
    n_years: int
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class Result:
    template: str
    crops: tuple[ScoredCrop, ...] = ()
    reasons: tuple[str, ...] = ()


def _window_open(window: str, sowing_date: date) -> bool:
    start_text, end_text = window.split("/")
    start = tuple(map(int, start_text.split("-")))
    end = tuple(map(int, end_text.split("-")))
    current = (sowing_date.month, sowing_date.day)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _demand(crop: Crop) -> float:
    value = crop.seasonal_water_demand
    if value <= 0:
        raise ValueError("Seasonal water demand must be positive")
    return value


def _score(
    crop: Crop,
    profile: Profile,
    indicator: Indicator,
    season: bool,
    demands: Mapping[str, float],
) -> ScoredCrop:
    adequate = indicator.n_adequate_elnino if season else indicator.n_adequate
    years = indicator.n_elnino if season else indicator.n_years
    reliability = adequate / years
    rotation = params.ROTATION_OTHER_BENEFIT
    if profile.last_crop == crop.name:
        rotation = 0.0
    elif profile.last_crop == "rice" and crop.is_legume:
        rotation = 1.0
    timing = 1 - max(indicator.heat_freq, indicator.harvest_rain_freq)
    priority = 0.0
    if profile.priority == "TUBIG":
        low, high = min(demands.values()), max(demands.values())
        priority = (high - demands[crop.name]) / (high - low) if high > low else 1.0
    elif profile.priority == "KITA":
        priority = crop.income_flag if crop.income_flag is not None else params.DEFAULT_INCOME_FLAG
    if not 0 <= priority <= 1:
        raise ValueError("Income flag must be between zero and one")
    reasons = [
        (
            "R_WATER_OK" if reliability >= params.WATER_OK_RELIABILITY else "R_WATER_SHORT",
            "water_reliability",
        )
    ]
    if profile.priority == "TUBIG" and priority > 0:
        reasons.append(("R_LESS_WATER", "farmer_priority"))
    if rotation == 1.0:
        reasons.append(("R_LEGUME", "rotation_benefit"))
    if profile.last_crop == crop.name:
        reasons.append(("R_SAME_CROP", "rotation_benefit"))
    if indicator.heat_freq > params.TIMING_REASON_FREQUENCY:
        reasons.append(("R_HEAT", "timing_risk"))
    if indicator.harvest_rain_freq > params.TIMING_REASON_FREQUENCY:
        reasons.append(("R_HARVEST_RAIN", "timing_risk"))
    components = {
        "water_reliability": reliability,
        "rotation_benefit": rotation,
        "timing_risk": timing,
        "farmer_priority": priority,
    }
    contributions = {key: params.SCORING_WEIGHTS[key] * value for key, value in components.items()}
    total = round(sum(contributions.values()), 6)
    # Stable sorting preserves the fixed reason order when contributions tie.
    ordered_reasons = tuple(
        code for code, _ in sorted(reasons, key=lambda reason: -contributions[reason[1]])
    )
    return ScoredCrop(
        crop.name, total, reliability, rotation, timing, priority, adequate, years, ordered_reasons
    )


def recommend(
    profile: Profile,
    indicators: Mapping[str, Indicator],
    crops: Sequence[Crop],
    season: bool,
) -> Result:
    """Rank candidates; season=True selects only El Nino historical counts.

    Only the top two are returned, matching the reply sketch. Ties sort by crop
    name. Missing season counts are treated as missing data, never as zero water
    reliability. The caller handles irrigation routing before invoking the engine.
    """
    candidates = []
    for crop in crops:
        indicator = indicators.get(crop.name)
        if indicator is None or indicator.barangay_code != profile.barangay_code:
            continue
        if not _window_open(indicator.sow_window, profile.sowing_date):
            continue
        years = indicator.n_elnino if season else indicator.n_years
        adequate = indicator.n_adequate_elnino if season else indicator.n_adequate
        if years <= 0:
            continue
        if not 0 <= adequate <= years:
            raise ValueError("Adequate count must be between zero and season count")
        if not all(0 <= value <= 1 for value in (indicator.heat_freq, indicator.harvest_rain_freq)):
            raise ValueError("Timing frequencies must be between zero and one")
        candidates.append(crop)
    if not candidates:
        return Result(template="T_NO_DATA")
    demands = (
        {crop.name: _demand(crop) for crop in candidates} if profile.priority == "TUBIG" else {}
    )
    ranked = sorted(
        (_score(crop, profile, indicators[crop.name], season, demands) for crop in candidates),
        key=lambda scored: (-scored.total, scored.name),
    )
    best = ranked[0]
    close_scores = len(ranked) > 1 and best.total - ranked[1].total <= params.BORDERLINE_SCORE_GAP
    low, high = params.BORDERLINE_WATER_RANGE
    if close_scores or low <= best.water_reliability <= high:
        return Result(template="T_PLANT_BORDER", crops=tuple(ranked[:2]))
    return Result(template="T_PLANT", crops=tuple(ranked[:2]), reasons=best.reason_codes)
