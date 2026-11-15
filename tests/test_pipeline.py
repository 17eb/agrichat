"""Offline numerical and integration checks for the indicator build."""

import csv
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.db import connect_db
from pipeline.budget import Crop, effective_rain, kc_curve, rain_table, season_budget
from pipeline.build_indicators import (
    DATA,
    FIELDS,
    build_indicators,
    conditions_now,
    load_crops,
    load_weather,
    summarize,
)
from pipeline.et0 import extraterrestrial_radiation, hargreaves, load_constants


def test_fao_radiation_example_and_et0() -> None:
    # FAO-56 Example 8: 3 September (J=246), 20 degrees south, Ra=32.2 MJ/m2/day.
    assert extraterrestrial_radiation(-20, 246, 0.0820) == pytest.approx(32.2, abs=0.1)
    # FAO-56 Annex 2 Table 2.6: January 15, 20 degrees north, Ra=26.8 MJ/m2/day.
    # Source: https://www.fao.org/4/x0490e/x0490e0j.htm (table image x0490e0u.jpg).
    assert extraterrestrial_radiation(20, 15, 0.0820) == pytest.approx(26.8, abs=0.1)
    # FAO-56 has no Hargreaves worked example; use Eq. 52 with Example 8 Ra.
    # Tmean=25, Tmax=30 and Tmin=20 are synthetic temperature inputs.
    expected = 0.0023 * (25 + 17.8) * 10**0.5 * 32.2 * 0.408
    assert hargreaves(25, 30, 20, -20, 246) == pytest.approx(expected, abs=0.1)
    constants = load_constants()
    constants["hargreaves_eto"] = "0.0046; 17.8; exponent 0.5"
    assert hargreaves(25, 30, 20, -20, 246, constants) == pytest.approx(2 * expected, abs=0.1)


def test_effective_rain() -> None:
    for rain, effective in rain_table():
        assert effective_rain(rain) == effective
    assert effective_rain(75) == 35.5
    assert effective_rain(15) == 1
    assert effective_rain(300) == 215
    with pytest.raises(ValueError):
        effective_rain(-1)


def test_kc_stages_scaled_to_da_days() -> None:
    for crop in load_crops():
        curve = kc_curve(crop)
        assert len(curve) == crop.days
        assert curve[0] == crop.kc_ini
        assert curve[-1] == pytest.approx(crop.kc_end)
        assert max(curve) == crop.kc_mid
    mungbean = next(crop for crop in load_crops() if crop.name == "mungbean")
    assert mungbean.stages == (20, 30, 30, 20)
    assert kc_curve(mungbean)[12] == mungbean.kc_ini
    assert kc_curve(mungbean)[13] > mungbean.kc_ini


def weather_days(start: date, days: int) -> dict[date, dict[str, float]]:
    return {
        start + timedelta(days=i): {
            "prectotcorr_mm": 0.0,
            "gwetroot": 0.5,
            "t2m_max_c": 25.0,
            "et0": 2.0,
        }
        for i in range(days)
    }


def test_exact_adequacy_and_rice_extra_demand() -> None:
    crop = Crop("rice", 4, 1, 1, 1, (1, 1, 1, 1))
    weather = weather_days(date(2025, 11, 1), 4)
    weather[date(2025, 11, 1)]["prectotcorr_mm"] = 50
    result = season_budget(crop, date(2025, 11, 1), weather, 100, 2)
    assert result == {"ratio": 7, "demand": 10, "supply": 70}


def test_elnino_join_and_incomplete_2025() -> None:
    crop = Crop("mungbean", 65, 0.4, 1.05, 0.475, (20, 30, 30, 20))
    weather = weather_days(date(2023, 11, 1), 65)
    weather.update(weather_days(date(2024, 11, 1), 65))
    weather.update(weather_days(date(2025, 11, 1), 61))
    row = summarize(crop, weather, {2023: True, 2024: False, 2025: True}, ((11, 1), (11, 30)))
    assert row["n_years"] == 2
    assert row["n_elnino"] == 1
    assert row["n_adequate_elnino"] == 0
    weather.update(weather_days(date(2026, 1, 1), 4))
    row = summarize(crop, weather, {2023: True, 2024: False, 2025: True}, ((11, 1), (11, 30)))
    assert row["n_years"] == 3
    assert row["n_elnino"] == 2


@pytest.fixture
def weather() -> dict[date, dict[str, float]]:
    return load_weather()


def test_smap_fallback_and_freshness(tmp_path: Path, weather: dict) -> None:
    path = tmp_path / "smap_now.csv"
    today = date(2026, 11, 15)
    fallback = conditions_now(weather, path, today)
    assert fallback["soilwet_source"] == "power"
    assert fallback["soilwet_date"] == "2026-11-11"
    for age, declared, source in (
        (0, 0, "smap"),
        (7, 7, "smap"),
        (8, 8, "power"),
        (20, 0, "power"),
        (0, 8, "power"),
    ):
        day = today - timedelta(days=age)
        path.write_text(
            "barangay_code,latest_date,soilwet_pct,days_since_latest\n"
            f"BATAC,{day},12.34,{declared}\n"
        )
        row = conditions_now(weather, path, today)
        assert row["soilwet_source"] == source
        assert row["soilwet_pct"] == (12.34 if source == "smap" else fallback["soilwet_pct"])

    header = "barangay_code,latest_date,soilwet_pct,days_since_latest\n"
    for missing in ("latest_date", "soilwet_pct", "days_since_latest"):
        fields = {
            "latest_date": today.isoformat(),
            "soilwet_pct": "12.34",
            "days_since_latest": "0",
        }
        fields[missing] = ""
        path.write_text(
            header + f"BATAC,{fields['latest_date']},{fields['soilwet_pct']},"
            f"{fields['days_since_latest']}\n"
        )
        assert conditions_now(weather, path, today) == fallback
    path.write_text(header + f"OTHER,{today},12.34,0\n")
    assert conditions_now(weather, path, today) == fallback


def test_build_repeatable_csv_and_database(tmp_path: Path) -> None:
    for directory in ("power", "crops", "oni", "barangays"):
        shutil.copytree(DATA / directory, tmp_path / directory)
    db = tmp_path / "indicators.db"
    first = build_indicators(tmp_path, db, date(2026, 11, 15))
    content = (tmp_path / "indicators.csv").read_bytes()
    second = build_indicators(tmp_path, db, date(2026, 11, 15))
    assert first == second
    assert content == (tmp_path / "indicators.csv").read_bytes()
    with (tmp_path / "indicators.csv").open(newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(FIELDS)
        assert len(list(reader)) == 3
    with connect_db(db) as connection:
        stored = [dict(row) for row in connection.execute("SELECT * FROM indicators ORDER BY crop")]
    assert stored == sorted(first, key=lambda row: row["crop"])
    assert {row["crop"] for row in first} == {"rice", "mungbean", "soybean"}
    assert all(row["n_years"] == 45 and row["n_elnino"] == 15 for row in first)


def test_heat_harvest_thresholds_and_adequacy_boundary() -> None:
    crop = Crop("mungbean", 20, 1, 1, 1, (5, 5, 5, 5))
    sowing = date(2023, 11, 1)
    weather = weather_days(sowing, 20)
    # 100 * 0.32 / (20 * 2) is exactly the adequacy threshold.
    for row in weather.values():
        row["gwetroot"] = 0.32
    weather[sowing + timedelta(days=10)]["t2m_max_c"] = 35
    weather[sowing + timedelta(days=19)]["prectotcorr_mm"] = 50
    row = summarize(crop, weather, {2023: True}, ((11, 1), (11, 30)))
    assert row["heat_freq"] == 1
    assert row["harvest_rain_freq"] == 1
    assert row["n_adequate"] == row["n_adequate_elnino"] == 1
    weather[sowing + timedelta(days=10)]["t2m_max_c"] = 34.99
    weather[sowing + timedelta(days=19)]["prectotcorr_mm"] = 0
    weather[sowing]["t2m_max_c"] = 40
    row = summarize(crop, weather, {2023: True}, ((11, 1), (11, 30)))
    assert row["heat_freq"] == row["harvest_rain_freq"] == 0
    assert row["median_ratio"] == 0.8
    assert row["n_adequate"] == 1


def test_same_date_historical_percentiles(tmp_path: Path) -> None:
    weather = {}
    for year, rain, soil in ((2024, 1, 0.1), (2025, 3, 0.9), (2026, 2, 0.5)):
        days = weather_days(date(year, 10, 13), 30)
        for row in days.values():
            row["prectotcorr_mm"] = rain
            row["gwetroot"] = soil
        weather.update(days)
    row = conditions_now(weather, tmp_path / "absent.csv", date(2026, 11, 15))
    assert row["rain30_pct"] == row["soilwet_pct"] == 50


def test_window_start_date_and_dry_season_year_offset() -> None:
    crop = Crop("mungbean", 20, 1, 1, 1, (5, 5, 5, 5))
    weather = weather_days(date(2024, 1, 1), 20)
    row = summarize(crop, weather, {2023: True, 2024: False}, ((1, 1), (1, 31)))
    assert row["n_years"] == row["n_elnino"] == 1
    other_end = summarize(crop, weather, {2023: True, 2024: False}, ((1, 1), (1, 15)))
    assert {key: value for key, value in row.items() if key != "sow_window"} == {
        key: value for key, value in other_end.items() if key != "sow_window"
    }
