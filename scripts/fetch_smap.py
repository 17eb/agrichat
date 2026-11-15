"""Fetch a single AppEEARS point and build the optional SMAP indicator files.

Run with EARTHDATA_USER and EARTHDATA_PASS in the environment. API reference:
https://appeears.earthdatacloud.nasa.gov/api/
"""

import argparse
import calendar
import csv
import json
import math
import os
import re
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from statistics import StatisticsError, correlation, mean
from typing import Any

import requests

DATA = Path(__file__).resolve().parents[1] / "data"
API = "https://appeears.earthdatacloud.nasa.gov/api"
PRODUCT = "SPL4SMGP.008"
PHT = timezone(timedelta(hours=8))
DAILY_FIELDS = (
    "barangay_code",
    "date",
    "sm_rootzone_m3m3",
    "sm_surface_m3m3",
    "sm_rootzone_wetness",
    "sm_rootzone_pctl_product",
    "n_obs",
    "soilwet_pct",
)
NOW_FIELDS = (
    "barangay_code",
    "latest_date",
    "sm_rootzone_m3m3",
    "soilwet_pct",
    "years_in_baseline",
    "days_since_latest",
)
META_FIELDS = (
    "product",
    "version",
    "layer",
    "unit",
    "fill_value",
    "pixel_lat",
    "pixel_lon",
    "first_date",
    "last_date",
    "task_id",
    "accessed_utc",
    "notes",
)
VARIABLES = {
    "sm_rootzone_m3m3": "sm_rootzone",
    "sm_surface_m3m3": "sm_surface",
    "sm_rootzone_wetness": "sm_rootzone_wetness",
    "sm_rootzone_pctl_product": "sm_rootzone_percentile",
}
LIMITS = (
    "Baseline starts in 2015 and includes few El Nino dry seasons. "
    "The 9 km model-assimilated pixel cannot resolve canal irrigation or individual fields. "
    "Model-only during instrument outages in mid-2019 and August-September 2022; "
    "consult retained bundle metadata for exact flagged dates. "
    "Percentiles count baseline values at or below the current value; "
    "the 31-day window is centered on the same month/day in each other year, "
    "wrapping within that year's length; February 29 maps to February 28 in non-leap years. "
    "n_obs counts valid root-zone observations; missing values are never interpolated."
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def select_layers(product: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Select exact advertised layer identifiers, rejecting ambiguous matches."""
    selected = {}
    for output, variable in VARIABLES.items():
        candidates = []
        for name, info in product.items():
            if not info.get("Available", True) or info.get("IsQA", False):
                continue
            # Product layer identifiers may include a group prefix.
            matches = name == variable or name.endswith("_" + variable)
            if output == "sm_rootzone_pctl_product":
                label = normalized(name + " " + info.get("Description", ""))
                matches = "rootzone" in label and ("percentile" in label or "pctl" in label)
            if matches:
                candidates.append((name, info))
        if len(candidates) == 1:
            selected[output] = candidates[0]
        elif candidates or output != "sm_rootzone_pctl_product":
            raise ValueError(f"Expected one advertised AppEEARS layer for {variable}")
    return selected


class AppEEARS:
    """Small HTTP boundary; tests supply a fake requests-compatible session."""

    def __init__(
        self,
        session: requests.Session,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session
        self.sleep = sleep
        self.clock = clock
        self.step = "login"
        self.task_path: Path | None = None

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        timeout = kwargs.pop("timeout", 30)
        response = self.session.request(method, API + path, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response

    def poll(self, task_id: str, deadline: float) -> str:
        """Retry status transport errors twice, keeping every attempt within the cap."""
        for attempt in range(3):
            remaining = deadline - self.clock()
            if remaining <= 60:
                raise TimeoutError("AppEEARS task exceeded the 3 hour polling cap")
            self.sleep(60)
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise TimeoutError("AppEEARS task exceeded the 3 hour polling cap")
            try:
                return self.request(
                    "GET",
                    f"/task/{task_id}",
                    timeout=min(30, remaining),
                ).json()["status"]
            except requests.RequestException:
                if attempt == 2:
                    raise
        raise AssertionError("Status polling exhausted without returning or raising")

    def download(
        self,
        username: str,
        password: str,
        raw: Path,
        end: date,
        latitude: float,
        longitude: float,
    ) -> tuple[str, dict[str, tuple[str, dict[str, Any]]], list[Path]]:
        self.step = "login"
        token = self.request("POST", "/login", auth=(username, password)).json()["token"]
        self.session.headers["Authorization"] = f"Bearer {token}"
        try:
            self.step = "product layers"
            product = self.request("GET", f"/product/{PRODUCT}").json()
            raw.mkdir(parents=True, exist_ok=True)
            (raw / "product_layers.json").write_text(json.dumps(product, indent=2))
            layers = select_layers(product)
            payload = {
                "task_type": "point",
                "task_name": "agrichat_smap_pilot",
                "params": {
                    "dates": [{"startDate": "03-31-2015", "endDate": end.strftime("%m-%d-%Y")}],
                    "layers": [{"product": PRODUCT, "layer": name} for name, _ in layers.values()],
                    "coordinates": [
                        {
                            "id": "pilot",
                            "category": "barangay",
                            "latitude": latitude,
                            "longitude": longitude,
                        }
                    ],
                },
            }
            (raw / "request.json").write_text(json.dumps(payload, indent=2))
            self.step = "task submit"
            task_id = self.request("POST", "/task", json=payload).json()["task_id"]
            self.task_path = raw / "task.json"
            self.task_path.write_text(
                json.dumps(
                    {
                        "task_id": task_id,
                        "accessed_utc": datetime.now(UTC).isoformat(),
                    }
                )
            )
            deadline = self.clock() + 3 * 60 * 60
            self.step = "task status poll"
            while True:
                status = self.poll(task_id, deadline)
                if status == "done":
                    break
                if status in {"error", "failed", "cancelled", "canceled"}:
                    raise ValueError("AppEEARS point task failed; inspect the task in AppEEARS")
            self.step = "bundle list"
            bundle = self.request("GET", f"/bundle/{task_id}").json()
            (raw / "bundle.json").write_text(json.dumps(bundle, indent=2))
            paths = []
            self.step = "bundle download"
            for entry in bundle["files"]:
                # Never allow a remote filename to escape the raw directory.
                path = raw / Path(entry["file_name"]).name
                response = self.request(
                    "GET",
                    f"/bundle/{task_id}/{entry['file_id']}",
                    stream=True,
                )
                try:
                    with path.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=65536):
                            handle.write(chunk)
                finally:
                    response.close()
                paths.append(path)
            self.task_path.write_text(
                json.dumps(
                    {
                        "task_id": task_id,
                        "accessed_utc": datetime.now(UTC).isoformat(),
                    }
                )
            )
            return task_id, layers, paths
        finally:
            try:
                self.request("POST", "/logout")
            except requests.RequestException:
                print("Warning: AppEEARS logout failed; local token cleared.", file=sys.stderr)
            finally:
                self.session.headers.pop("Authorization", None)


def timestamp(row: dict[str, str]) -> datetime:
    columns = {normalized(key): value for key, value in row.items()}
    value = columns.get("datetime") or columns.get("timestamp") or columns.get("date")
    if not value:
        raise ValueError("AppEEARS results lack a date-time column")
    if columns.get("time") and "T" not in value and " " not in value:
        value += "T" + columns["time"]
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def value_column(columns: list[str], layer: str) -> str:
    matches = [key for key in columns if normalized(key).endswith(normalized(layer))]
    if len(matches) != 1:
        raise ValueError(f"Expected one results column for layer {layer}")
    return matches[0]


def measurement(text: str, info: dict[str, Any]) -> float | None:
    if not text.strip():
        return None
    value = float(text)
    if not math.isfinite(value):
        return None
    fill = info.get("FillValue")
    if fill not in (None, "") and value == float(fill):
        return None
    # AppEEARS point CSV values are already scaled physical values.
    for key, invalid in (
        ("ValidMin", lambda bound: value < bound),
        ("ValidMax", lambda bound: value > bound),
    ):
        if info.get(key) not in (None, "") and invalid(float(info[key])):
            return None
    return value


class BaselineIndex:
    """Index valid daily values so each query visits only 31 days per other year."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.years: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
        for row in rows:
            if row["sm_rootzone_m3m3"] is not None:
                day = date.fromisoformat(row["date"])
                self.years[day.year][day.timetuple().tm_yday] = row

    def rows(self, day: date) -> list[dict[str, Any]]:
        result = []
        for year, values in self.years.items():
            if year == day.year:
                continue
            leap = calendar.isleap(year)
            month_day = 28 if day.month == 2 and day.day == 29 and not leap else day.day
            center = date(year, day.month, month_day).timetuple().tm_yday
            year_length = 366 if leap else 365
            for offset in range(-15, 16):
                other = values.get((center + offset - 1) % year_length + 1)
                if other is not None:
                    result.append(other)
        return result


def baseline_rows(day: date, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return BaselineIndex(rows).rows(day)


def daily_means(
    paths: list[Path],
    layers: dict[str, tuple[str, dict[str, Any]]],
    barangay: str,
) -> tuple[list[dict[str, Any]], tuple[str, str]]:
    groups: dict[date, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    seen = set()
    pixel = ("", "")
    for path in paths:
        for row in read_csv(path):
            instant = timestamp(row)
            if instant in seen:
                raise ValueError("Duplicate AppEEARS observation timestamp")
            seen.add(instant)
            day = instant.astimezone(PHT).date()
            group = groups[day]
            for output, (layer, info) in layers.items():
                value = measurement(row[value_column(list(row), layer)], info)
                if value is not None:
                    group[output].append(value)
            # Only explicitly returned pixel coordinates qualify, not the input point.
            keys = {normalized(key): value for key, value in row.items()}
            pixel = (
                keys.get("pixellat", keys.get("pixellatitude", pixel[0])),
                keys.get("pixellon", keys.get("pixellongitude", pixel[1])),
            )
    rows = []
    for day, values in sorted(groups.items()):
        rows.append(
            {
                "barangay_code": barangay,
                "date": day.isoformat(),
                **{key: mean(values[key]) if values[key] else None for key in VARIABLES},
                "n_obs": len(values["sm_rootzone_m3m3"]),
                "soilwet_pct": None,
            }
        )
    index = BaselineIndex(rows)
    for row in rows:
        baseline = index.rows(date.fromisoformat(row["date"]))
        if baseline and row["sm_rootzone_m3m3"] is not None:
            row["soilwet_pct"] = (
                100
                * sum(other["sm_rootzone_m3m3"] <= row["sm_rootzone_m3m3"] for other in baseline)
                / len(baseline)
            )
    return rows, pixel


def compare_power(rows: list[dict[str, Any]], path: Path, barangay: str) -> dict[str, Any]:
    result = {"n_days": 0, "pearson_r": None, "mean_diff": None, "note": "POWER file absent"}
    if not path.exists():
        return result
    power = {
        row["date"]: float(row["gwetroot"])
        for row in read_csv(path)
        if row["barangay_code"] == barangay
        and row["gwetroot"].strip()
        and math.isfinite(float(row["gwetroot"]))
    }
    pairs = [
        (row["sm_rootzone_wetness"], power[row["date"]])
        for row in rows
        if "2015-01-01" <= row["date"] <= "2025-12-31"
        and row["date"] in power
        and row["sm_rootzone_wetness"] is not None
    ]
    if not pairs:
        return result | {"note": "No overlapping valid days in 2015-2025"}
    smap, wetness = zip(*pairs, strict=True)
    result.update(
        n_days=len(pairs), mean_diff=mean(a - b for a, b in pairs), note="SMAP minus POWER"
    )
    try:
        result["pearson_r"] = correlation(smap, wetness)
    except StatisticsError:
        result["note"] += "; correlation undefined (too few days or constant series)"
    return result


def process_results(
    paths: list[Path],
    layers: dict[str, tuple[str, dict[str, Any]]],
    task_id: str,
    data: Path,
    barangay: str,
    accessed: datetime,
) -> None:
    results = [path for path in paths if path.name.lower().endswith("results.csv")]
    if not results:
        raise ValueError("AppEEARS bundle contains no results CSV")
    rows, pixel = daily_means(results, layers, barangay)
    valid = [row for row in rows if row["sm_rootzone_m3m3"] is not None]
    if not valid:
        raise ValueError("AppEEARS results contain no valid root-zone observations")
    latest = valid[-1]
    day = date.fromisoformat(latest["date"])
    baseline = baseline_rows(day, rows)
    now = {
        "barangay_code": barangay,
        "latest_date": latest["date"],
        "sm_rootzone_m3m3": latest["sm_rootzone_m3m3"],
        "soilwet_pct": latest["soilwet_pct"],
        "years_in_baseline": len({row["date"][:4] for row in baseline}),
        "days_since_latest": (accessed.astimezone(PHT).date() - day).days,
    }
    metadata = [
        {
            "product": "SPL4SMGP",
            "version": "008",
            "layer": layer,
            "unit": info.get("Units", ""),
            "fill_value": info.get("FillValue", ""),
            "pixel_lat": pixel[0],
            "pixel_lon": pixel[1],
            "first_date": rows[0]["date"],
            "last_date": rows[-1]["date"],
            "task_id": task_id,
            "accessed_utc": accessed.astimezone(UTC).isoformat(),
            "notes": LIMITS
            + (" Pixel coordinates not returned in results." if not all(pixel) else ""),
        }
        for layer, info in layers.values()
    ]
    output = data / "smap"
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "smap_l4_daily.csv", DAILY_FIELDS, rows)
    write_csv(output / "smap_now.csv", NOW_FIELDS, [now])
    comparison = compare_power(rows, data / "power/power_daily_1981_2025.csv", barangay)
    write_csv(
        output / "smap_vs_power.csv", ("n_days", "pearson_r", "mean_diff", "note"), [comparison]
    )
    write_csv(output / "smap_metadata.csv", META_FIELDS, metadata)


def process_raw(
    raw_dir: Path,
    data: Path,
    barangay: str,
    accessed: datetime | None = None,
) -> None:
    """Rebuild outputs from retained files, preserving their original fetch timestamp."""
    product = json.loads((raw_dir / "product_layers.json").read_text())
    task = json.loads((raw_dir / "task.json").read_text())
    saved_accessed = task.get("accessed_utc")
    if saved_accessed:
        accessed = datetime.fromisoformat(saved_accessed.replace("Z", "+00:00"))
    if accessed is None or accessed.tzinfo is None:
        raise ValueError("Retained task must include a timezone-aware accessed_utc")
    process_results(
        sorted(raw_dir.glob("*results.csv")),
        select_layers(product),
        task["task_id"],
        data,
        barangay,
        accessed,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--process-only", action="store_true", help="Rebuild from data/smap/raw offline"
    )
    args = parser.parse_args(argv or [])
    if not args.process_only:
        username, password = os.environ.get("EARTHDATA_USER"), os.environ.get("EARTHDATA_PASS")
        if not username or not password:
            print(
                "Set EARTHDATA_USER and EARTHDATA_PASS to fetch SMAP from AppEEARS.",
                file=sys.stderr,
            )
            return 2
    raw = DATA / "smap/raw"
    client = None
    step = "read pilot coordinates"
    try:
        if not args.process_only:
            pilot = next(
                row
                for row in read_csv(DATA / "barangays/barangays.csv")
                if row["barangay_code"] == "BATAC"
            )
            with requests.Session() as session:
                client = AppEEARS(session)
                step = "download"
                client.download(
                    username,
                    password,
                    raw,
                    datetime.now(PHT).date(),
                    float(pilot["lat"]),
                    float(pilot["lon"]),
                )
        step = "process raw"
        process_raw(raw, DATA, "BATAC")
    except (
        requests.RequestException,
        OSError,
        ValueError,
        KeyError,
        StopIteration,
        TimeoutError,
    ) as error:
        if step == "download" and client is not None:
            step = client.step
        # Report only safe diagnostic fields, never exception text, response bodies or URLs.
        detail = type(error).__name__
        if isinstance(error, requests.RequestException) and error.response is not None:
            detail += f"; HTTP {error.response.status_code}"
        context = (
            f"; retained task: {raw / 'task.json'}"
            if (
                (client is not None and client.task_path is not None)
                or (raw / "task.json").exists()
            )
            else ""
        )
        print(f"SMAP fetch failed at {step} ({detail}){context}.", file=sys.stderr)
        return 1
    print("Wrote SMAP daily, now, comparison and metadata CSV files in data/smap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
