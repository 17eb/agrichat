"""Validate the optional SMAP daily record: python scripts/check_smap.py."""

import csv
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

DATA = Path(__file__).resolve().parents[1] / "data/smap/smap_l4_daily.csv"
START = date(2015, 3, 31)


def check_rows(rows: list[dict[str, str]], fetched_on: date) -> tuple[list[str], list[str]]:
    """Return failures and observations, including every missing calendar day."""
    errors, reports = [], []
    if not rows:
        return ["SMAP daily CSV is empty"], reports
    days = [date.fromisoformat(row["date"]) for row in rows]
    if len(set(days)) != len(days):
        errors.append("Duplicate dates in SMAP daily CSV")
    if days != sorted(days):
        errors.append("SMAP dates are not sorted")
    if min(days) != START:
        errors.append("SMAP record must begin on 2015-03-31")
    present = {
        day
        for row, day in zip(rows, days, strict=True)
        if all(
            row[key].strip()
            for key in (
                "sm_rootzone_m3m3",
                "sm_surface_m3m3",
                "sm_rootzone_wetness",
            )
        )
        and int(row["n_obs"]) > 0
    }
    gaps = []
    day = START
    while day <= max(days):
        if day not in present:
            gaps.append(day.isoformat())
        day += timedelta(days=1)
    reports.append(f"Missing days: {len(gaps)}" + (": " + ", ".join(gaps) if gaps else ""))
    if gaps:
        errors.append("SMAP record has missing days")
    dry, wet = [], []
    incomplete = 0
    valid_days = []
    for row, day in zip(rows, days, strict=True):
        for key, upper in (
            ("sm_rootzone_m3m3", 0.9),
            ("sm_surface_m3m3", 0.9),
            ("sm_rootzone_wetness", 1),
        ):
            if not row[key].strip():
                continue
            value = float(row[key])
            if not math.isfinite(value) or not 0 <= value <= upper:
                errors.append(f"{day}: {key} must be finite and between 0 and {upper}")
            elif key == "sm_rootzone_m3m3":
                valid_days.append(day)
                if 2 <= day.month <= 4:
                    dry.append(value)
                elif 7 <= day.month <= 9:
                    wet.append(value)
        n_obs = int(row["n_obs"])
        incomplete += n_obs != 8
        if not 0 <= n_obs <= 8:
            errors.append(f"{day}: n_obs must be between 0 and 8")
        for key in ("soilwet_pct", "sm_rootzone_pctl_product"):
            if row[key] and not 0 <= float(row[key]) <= 100:
                errors.append(f"{day}: {key} must be between 0 and 100")
    reports.append(f"Days with n_obs != 8: {incomplete}/{len(rows)} ({incomplete / len(rows):.1%})")
    if incomplete * 2 >= len(rows):
        errors.append("Most SMAP days must have n_obs = 8")
    if not dry or not wet:
        errors.append("Cannot compare dry and wet months: both seasonal samples are required")
    else:
        reports.append(f"Dry-month mean: {mean(dry):.6f}; wet-month mean: {mean(wet):.6f}")
        if mean(dry) >= mean(wet):
            errors.append("February-April must be drier than July-September")
    if valid_days:
        lag = (fetched_on - max(valid_days)).days
        reports.append(f"Latest SMAP data lag at fetch ({fetched_on} PHT): {lag} days")
        if not 0 <= lag <= 7:
            errors.append("Latest valid SMAP date must be within the last 7 days before fetch")
    else:
        errors.append("No valid root-zone data")
    return errors, reports


def main() -> int:
    try:
        with DATA.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        metadata_path = DATA.with_name("smap_metadata.csv")
        with metadata_path.open(newline="", encoding="utf-8-sig") as handle:
            metadata = list(csv.DictReader(handle))
        if not metadata:
            raise ValueError("SMAP metadata must contain accessed_utc")
        accessed = [
            datetime.fromisoformat(row["accessed_utc"].replace("Z", "+00:00")) for row in metadata
        ]
        if any(value.tzinfo is None for value in accessed):
            raise ValueError("SMAP metadata accessed_utc must include a timezone")
        if len(set(accessed)) != 1:
            raise ValueError("SMAP metadata contains inconsistent fetch timestamps")
        fetched_on = accessed[0].astimezone(timezone(timedelta(hours=8))).date()
        errors, reports = check_rows(rows, fetched_on)
    except (OSError, ValueError, KeyError, csv.Error) as error:
        print(f"SMAP check failed: {error}", file=sys.stderr)
        return 1
    for report in reports:
        print(report)
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
