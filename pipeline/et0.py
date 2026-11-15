"""FAO-56 Hargreaves ET0; Kc was calibrated for Penman-Monteith ET0."""

import csv
import math
from pathlib import Path

CONSTANTS = Path(__file__).resolve().parents[1] / "data/crops/method_constants.csv"


def load_constants(path: Path = CONSTANTS) -> dict[str, str]:
    with path.open(newline="") as handle:
        return {row["name"]: row["coefficient_values"] for row in csv.DictReader(handle)}


def extraterrestrial_radiation(latitude: float, day_of_year: int, gsc: float) -> float:
    """FAO-56 Eq. 21, in MJ/m2/day, including polar day/night limits."""
    phi = math.radians(latitude)
    dr = 1 + 0.033 * math.cos(2 * math.pi * day_of_year / 365)
    delta = 0.409 * math.sin(2 * math.pi * day_of_year / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    return (
        24
        * 60
        / math.pi
        * gsc
        * dr
        * (ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws))
    )


def hargreaves(
    tmean: float,
    tmax: float,
    tmin: float,
    latitude: float,
    day_of_year: int,
    constants: dict[str, str] | None = None,
) -> float:
    """FAO-56 Eq. 52 using the observed mean and Ra converted to mm/day."""
    constants = load_constants() if constants is None else constants
    coefficient, offset, exponent = constants["hargreaves_eto"].split(";")
    gsc = float(constants["extraterrestrial_radiation_ra"].split(";")[0].split("=")[1])
    if tmax < tmin:
        raise ValueError("Maximum temperature is below minimum temperature")
    ra = extraterrestrial_radiation(latitude, day_of_year, gsc)
    return max(
        0.0,
        float(coefficient)
        * (tmean + float(offset))
        * (tmax - tmin) ** float(exponent.split()[-1])
        * ra
        * float(constants["ra_to_mm_per_day"]),
    )
