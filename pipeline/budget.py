"""Rainfed crop budgets from FAO Table 6 and scaled FAO-56 stage curves."""

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

from pipeline.et0 import load_constants


@dataclass(frozen=True)
class Crop:
    name: str
    days: int
    kc_ini: float
    kc_mid: float
    kc_end: float
    stages: tuple[float, float, float, float]


def rain_table() -> list[tuple[float, float]]:
    text = load_constants()["effective_rainfall_monthly"]
    return [tuple(map(float, pair.split(":"))) for pair in text.split(";")[1:]]


def effective_rain(rain_mm: float, pairs: list[tuple[float, float]] | None = None) -> float:
    """FAO Training Manual 3 Table 6; assume its final slope beyond 250 mm.

    Method limit: partial first/last crop months use only in-crop rain against
    this monthly table, without prorating its monthly effective-rain values.
    """
    if rain_mm < 0:
        raise ValueError("Rain cannot be negative")
    pairs = rain_table() if pairs is None else pairs
    left, right = pairs[-2:]
    for lower, upper in pairwise(pairs):
        if rain_mm <= upper[0]:
            left, right = lower, upper
            break
    return left[1] + (rain_mm - left[0]) * (right[1] - left[1]) / (right[0] - left[0])


def stage_boundaries(crop: Crop) -> tuple[float, float, float, float]:
    total = sum(crop.stages)
    ini, dev, mid, _ = crop.stages
    return tuple(crop.days * value / total for value in (ini, ini + dev, ini + dev + mid, total))


def kc_curve(crop: Crop) -> list[float]:
    """Sample the stage curve at daily endpoints; the last day reaches kc_end."""
    initial, development, middle, end = stage_boundaries(crop)
    values = []
    for day in range(1, crop.days + 1):
        if day <= initial:
            kc = crop.kc_ini
        elif day < development:
            kc = crop.kc_ini + (crop.kc_mid - crop.kc_ini) * (
                (day - initial) / (development - initial)
            )
        elif day <= middle:
            kc = crop.kc_mid
        else:
            kc = crop.kc_mid + (crop.kc_end - crop.kc_mid) * ((day - middle) / (end - middle))
        values.append(kc)
    return values


def season_budget(
    crop: Crop,
    sowing: date,
    weather: dict[date, dict[str, float]],
    capacity_mm: float,
    rice_allowance_mm: float,
) -> dict[str, float] | None:
    """A for ULAN only; partial months use crop-period rain, with no irrigation.

    Starting water is simplified to POWER gwetroot times a fixed capacity.
    Rice soaking/seepage is added to demand, never to water supply.
    """
    dates = [sowing + timedelta(days=day) for day in range(crop.days)]
    if any(day not in weather for day in dates):
        return None
    months: dict[tuple[int, int], float] = {}
    demand = rice_allowance_mm if crop.name == "rice" else 0.0
    for day, kc in zip(dates, kc_curve(crop), strict=True):
        key = (day.year, day.month)
        months[key] = months.get(key, 0.0) + weather[day]["prectotcorr_mm"]
        demand += kc * weather[day]["et0"]
    if demand <= 0:
        raise ValueError("Crop water demand must be positive")
    supply = sum(effective_rain(rain) for rain in months.values())
    supply += weather[sowing]["gwetroot"] * capacity_mm
    return {"ratio": supply / demand, "demand": demand, "supply": supply}
