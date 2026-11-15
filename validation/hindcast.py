"""Hindcast: seasons flagged water-short against El Nino seasons and a rainfall baseline.

Run: python -m validation.hindcast

For each crop and each past dry season, two rules flag the season as water-short:
- engine: the water ratio A is below ``params.ADEQUACY_THRESHOLD``.
- baseline: crop-period rain is below the average over all tested seasons.
Both flags are compared with the El Nino label in ``data/oni/enso_dry_seasons.csv``,
which is read as built by the fixed ENSO rule and never recomputed here.
The same seasons are used for both rules, and nothing is tuned to the result.
"""

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean

from engine import params
from pipeline.budget import Crop
from pipeline.build_indicators import (
    load_crops,
    load_enso,
    load_weather,
    season_budgets,
)

RESULTS = Path(__file__).resolve().parent / "results"
FIELDS = (
    "crop",
    "method",
    "n_seasons",
    "n_elnino",
    "n_flagged",
    "hits",
    "misses",
    "false_alarms",
    "correct_negatives",
)
METHODS = ("engine", "baseline")


@dataclass(frozen=True)
class Season:
    year: int
    ratio: float
    rain_mm: float


@dataclass(frozen=True)
class Confusion:
    hits: int
    misses: int
    false_alarms: int
    correct_negatives: int

    @property
    def n_seasons(self) -> int:
        return self.hits + self.misses + self.false_alarms + self.correct_negatives

    @property
    def n_elnino(self) -> int:
        return self.hits + self.misses

    @property
    def n_flagged(self) -> int:
        return self.hits + self.false_alarms


def crop_seasons(
    crop: Crop,
    weather: dict[date, dict[str, float]],
    years: list[int],
    sow_window: tuple[tuple[int, int], tuple[int, int]] = params.SOWING_WINDOW,
) -> list[Season]:
    """Water ratio and crop-period rain per season, from the same budgets as the indicators."""
    return [
        Season(
            year,
            budget["ratio"],
            sum(weather[sowing + timedelta(days=i)]["prectotcorr_mm"] for i in range(crop.days)),
        )
        for year, sowing, budget in season_budgets(crop, weather, years, sow_window)
    ]


def engine_flags(seasons: list[Season]) -> dict[int, bool]:
    return {s.year: s.ratio < params.ADEQUACY_THRESHOLD for s in seasons}


def baseline_flags(seasons: list[Season]) -> dict[int, bool]:
    """Rainfall-only rule: short when crop-period rain is below the average of all seasons."""
    average = fmean(s.rain_mm for s in seasons)
    return {s.year: s.rain_mm < average for s in seasons}


def confusion(flags: dict[int, bool], elnino: dict[int, bool]) -> Confusion:
    """Hit: flagged El Nino. Miss: unflagged El Nino. False alarm: flagged non-El Nino."""
    counts = {"hits": 0, "misses": 0, "false_alarms": 0, "correct_negatives": 0}
    for year, flagged in flags.items():
        if elnino[year]:
            counts["hits" if flagged else "misses"] += 1
        else:
            counts["false_alarms" if flagged else "correct_negatives"] += 1
    return Confusion(**counts)


def run(
    weather: dict[date, dict[str, float]],
    crops: list[Crop],
    elnino: dict[int, bool],
) -> list[dict[str, str | int]]:
    rows = []
    for crop in crops:
        seasons = crop_seasons(crop, weather, list(elnino))
        if not seasons:
            raise ValueError(f"No complete seasons for {crop.name}")
        rules = {"engine": engine_flags(seasons), "baseline": baseline_flags(seasons)}
        for method in METHODS:
            result = confusion(rules[method], elnino)
            rows.append(
                {
                    "crop": crop.name,
                    "method": method,
                    "n_seasons": result.n_seasons,
                    "n_elnino": result.n_elnino,
                    "n_flagged": result.n_flagged,
                    "hits": result.hits,
                    "misses": result.misses,
                    "false_alarms": result.false_alarms,
                    "correct_negatives": result.correct_negatives,
                }
            )
    return rows


def share(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.0f}%" if denominator else "n/a"


def summary_markdown(rows: list[dict[str, str | int]]) -> str:
    lines = [
        "# Hindcast summary",
        "",
        "Each past dry season at the pilot site is flagged water-short "
        "by the engine rule or by a rainfall-only baseline.",
        f"The engine flags a season when the water ratio A is below {params.ADEQUACY_THRESHOLD}.",
        "The baseline flags a season when crop-period rain "
        "is below the average of all tested seasons.",
        "Both are compared with the El Nino seasons from the NOAA index.",
        "A hit is a flagged El Nino season, a miss is an unflagged El Nino season, "
        "and a false alarm is a flagged season that is not El Nino.",
        "",
        "| Crop | Rule | Seasons | El Nino | Flagged | Hits | Misses | False alarms "
        "| El Nino caught | Non-El Nino flagged |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        non_elnino = int(row["n_seasons"]) - int(row["n_elnino"])
        lines.append(
            f"| {row['crop']} | {row['method']} | {row['n_seasons']} | {row['n_elnino']} "
            f"| {row['n_flagged']} | {row['hits']} | {row['misses']} | {row['false_alarms']} "
            f"| {share(int(row['hits']), int(row['n_elnino']))} "
            f"| {share(int(row['false_alarms']), non_elnino)} |"
        )
    lines += [
        "",
        "Limits: one pilot point, no yield data, and a flagged season is not a crop failure.",
        "A season whose crop period runs past the last full weather row is left out "
        "and shows in the season count.",
        "The thresholds are reviewer placeholders in `engine/params.py` "
        "and were not tuned to these results.",
        "",
    ]
    return "\n".join(lines)


def write_results(rows: list[dict[str, str | int]], results: Path = RESULTS) -> None:
    results.mkdir(parents=True, exist_ok=True)
    with (results / "hindcast.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (results / "hindcast.md").write_text(summary_markdown(rows), encoding="utf-8")


def main() -> None:
    rows = run(load_weather(), load_crops(), load_enso())
    write_results(rows)


if __name__ == "__main__":
    main()
