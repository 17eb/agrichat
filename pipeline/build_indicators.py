"""Build offline BATAC indicators: python -m pipeline.build_indicators.

Only standard-library CSV, math and statistics are used for numerical work.
Percentiles use the percentage of historical values at or below today's value.
"""

import csv
from datetime import date, timedelta
from pathlib import Path
from statistics import median

from app.config import Settings
from app.db import connect_db, init_db
from engine import params
from pipeline.budget import Crop, season_budget, stage_boundaries
from pipeline.et0 import hargreaves, load_constants

DATA = Path(__file__).resolve().parents[1] / "data"
DRY_SEASON_START_MONTH = 11
FIELDS = (
    "barangay_code",
    "crop",
    "sow_window",
    "n_years",
    "n_adequate",
    "n_elnino",
    "n_adequate_elnino",
    "median_ratio",
    "heat_freq",
    "harvest_rain_freq",
    "rain30_pct",
    "soilwet_pct",
    "soilwet_source",
    "soilwet_date",
    "updated_at",
)
WEATHER_FIELDS = ("prectotcorr_mm", "t2m_max_c", "t2m_min_c", "t2m_mean_c", "gwetroot")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def load_weather(data: Path = DATA) -> dict[date, dict[str, float]]:
    constants = load_constants(data / "crops/method_constants.csv")
    latitude = float(
        next(
            row
            for row in read_csv(data / "barangays/barangays.csv")
            if row["barangay_code"] == "BATAC"
        )["lat"]
    )
    weather = {}
    for path in sorted((data / "power").glob("power_daily_*.csv")):
        for row in read_csv(path):
            if row["barangay_code"] != "BATAC" or any(not row[key] for key in WEATHER_FIELDS):
                continue
            values = {key: float(row[key]) for key in WEATHER_FIELDS}
            day = date.fromisoformat(row["date"])
            values["et0"] = hargreaves(
                values["t2m_mean_c"],
                values["t2m_max_c"],
                values["t2m_min_c"],
                latitude,
                day.timetuple().tm_yday,
                constants,
            )
            weather[day] = values
    if not weather:
        raise ValueError("No complete POWER weather rows")
    return weather


def load_crops(data: Path = DATA) -> list[Crop]:
    stages = {
        row["crop"]: tuple(
            float(row[key]) for key in ("l_ini_days", "l_dev_days", "l_mid_days", "l_late_days")
        )
        for row in read_csv(data / "crops/fao56_stage_lengths.csv")
        if row["suggested"] == "1"
    }
    return [
        Crop(
            row["crop"],
            int(row["days"]),
            float(row["kc_ini"]),
            float(row["kc_mid"]),
            params.KC_END[row["crop"]],
            stages[row["crop"]],
        )
        for row in read_csv(data / "crops/crops_engine.csv")
        if row["crop"] in params.KC_END
    ]


def percentile(value: float, baseline: list[float]) -> float:
    if not baseline:
        raise ValueError("Historical percentile requires a baseline")
    return 100 * sum(item <= value for item in baseline) / len(baseline)


def conditions_now(
    weather: dict[date, dict[str, float]],
    smap_path: Path,
    as_of: date,
) -> dict[str, str | float]:
    latest = max(weather)

    def rain30(end: date) -> float | None:
        days = [end - timedelta(days=i) for i in range(30)]
        if any(day not in weather for day in days):
            return None
        return sum(weather[day]["prectotcorr_mm"] for day in days)

    rain_baseline, soil_baseline = [], []
    for day in sorted(weather):
        if day.year >= latest.year or (day.month, day.day) != (latest.month, latest.day):
            continue
        rain = rain30(day)
        if rain is not None:
            rain_baseline.append(rain)
        soil_baseline.append(weather[day]["gwetroot"])
    current_rain = rain30(latest)
    if current_rain is None:
        raise ValueError("Latest POWER date lacks 30 complete rain days")
    result: dict[str, str | float] = {
        "rain30_pct": percentile(current_rain, rain_baseline),
        "soilwet_pct": percentile(weather[latest]["gwetroot"], soil_baseline),
        "soilwet_source": "power",
        "soilwet_date": latest.isoformat(),
    }
    if smap_path.exists():
        for row in read_csv(smap_path):
            if row["barangay_code"] != "BATAC" or any(
                not row[key].strip() for key in ("latest_date", "soilwet_pct", "days_since_latest")
            ):
                continue
            smap_date = date.fromisoformat(row["latest_date"])
            age = (as_of - smap_date).days
            if 0 <= age <= 7 and int(row["days_since_latest"]) <= 7:
                result.update(
                    soilwet_pct=float(row["soilwet_pct"]),
                    soilwet_source="smap",
                    soilwet_date=smap_date.isoformat(),
                )
    return result


def summarize(
    crop: Crop,
    weather: dict[date, dict[str, float]],
    enso: dict[int, bool],
    sow_window: tuple[tuple[int, int], tuple[int, int]],
) -> dict[str, str | float | int]:
    """Score each window at its start date; flowering is the scaled mid stage.

    Dry-season years begin in November and include sowing early in the next year.
    """
    start, end = sow_window
    ratios, adequate, elnino_adequate = [], [], []
    heat, harvest_rain = [], []
    _, flower_start, flower_end, _ = stage_boundaries(crop)
    for year in sorted(enso):
        sowing = date(year + (start[0] < DRY_SEASON_START_MONTH), *start)
        budget = season_budget(
            crop,
            sowing,
            weather,
            params.ROOT_ZONE_WATER_CAPACITY_MM,
            params.RICE_EXTRA_ALLOWANCE_MM,
        )
        if budget is None:
            continue
        ratio = budget["ratio"]
        ratios.append(ratio)
        enough = ratio >= params.ADEQUACY_THRESHOLD
        adequate.append(enough)
        if enso[year]:
            elnino_adequate.append(enough)
        heat.append(
            any(
                weather[sowing + timedelta(days=i)]["t2m_max_c"] >= params.HEAT_THRESHOLD_C
                for i in range(crop.days)
                if flower_start < i + 1 <= flower_end
            )
        )
        harvest_rain.append(
            any(
                weather[sowing + timedelta(days=i)]["prectotcorr_mm"]
                >= params.HARVEST_RAIN_THRESHOLD_MM
                for i in range(max(0, crop.days - 14), crop.days)
            )
        )
    if not ratios:
        raise ValueError(f"No complete seasons for {crop.name}")
    return {
        "barangay_code": "BATAC",
        "crop": crop.name,
        "sow_window": f"{start[0]:02d}-{start[1]:02d}/{end[0]:02d}-{end[1]:02d}",
        "n_years": len(ratios),
        "n_adequate": sum(adequate),
        "n_elnino": len(elnino_adequate),
        "n_adequate_elnino": sum(elnino_adequate),
        "median_ratio": median(ratios),
        "heat_freq": sum(heat) / len(ratios),
        "harvest_rain_freq": sum(harvest_rain) / len(ratios),
    }


def build_indicators(
    data: Path = DATA,
    db_path: str | Path | None = None,
    as_of: date | None = None,
) -> list[dict[str, str | float | int]]:
    weather = load_weather(data)
    enso = {
        int(row["dry_season_start_year"]): row["el_nino"] == "1"
        for row in read_csv(data / "oni/enso_dry_seasons.csv")
    }
    current = conditions_now(weather, data / "smap/smap_now.csv", as_of or date.today())
    rows = [
        summarize(crop, weather, enso, params.SOWING_WINDOW)
        | current
        | {"updated_at": max(weather).isoformat()}
        for crop in load_crops(data)
    ]
    init_db(db_path or Settings.from_env().db_path)
    with connect_db(db_path or Settings.from_env().db_path) as connection:
        connection.execute("DELETE FROM indicators WHERE barangay_code = ?", ("BATAC",))
        connection.executemany(
            """INSERT INTO indicators (
                barangay_code, crop, sow_window, n_years, n_adequate, n_elnino,
                n_adequate_elnino, median_ratio, heat_freq, harvest_rain_freq,
                rain30_pct, soilwet_pct, soilwet_source, soilwet_date, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [tuple(row[key] for key in FIELDS) for row in rows],
        )
    with (data / "indicators.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    build_indicators()
