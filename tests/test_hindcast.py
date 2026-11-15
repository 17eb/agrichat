"""Hindcast confusion counts on a small synthetic dataset with a known answer."""

import csv
from datetime import date
from pathlib import Path

import pytest

from engine import params
from pipeline.budget import Crop
from pipeline.build_indicators import load_enso
from validation import hindcast
from validation.hindcast import Season

# year: (daily rain mm, root-zone wetness, El Nino)
SEASONS = {
    2000: (0.5, 0.0, True),
    2001: (0.5, 0.0, True),
    2002: (20.0, 0.5, True),
    2003: (0.5, 0.0, False),
    2004: (1.0, 0.5, False),
    2005: (10.0, 0.5, False),
}
CROP = Crop("mungbean", 2, 1.0, 1.0, 1.0, (1.0, 1.0, 1.0, 1.0))


def synthetic() -> tuple[dict[date, dict[str, float]], dict[int, bool]]:
    weather = {
        date(year, 11, day): {"prectotcorr_mm": rain, "gwetroot": wet, "et0": 4.0}
        for year, (rain, wet, _) in SEASONS.items()
        for day in (1, 2)
    }
    return weather, {year: values[2] for year, values in SEASONS.items()}


def test_known_confusion_matrix() -> None:
    weather, elnino = synthetic()
    rows = hindcast.run(weather, [CROP], elnino)
    counts = {
        row["method"]: tuple(
            row[key] for key in ("hits", "misses", "false_alarms", "correct_negatives")
        )
        for row in rows
    }
    # Engine short in 2000, 2001, 2003 (ratio 0.125); baseline: rain below mean 65/6 = 10.83 mm.
    assert counts["engine"] == (2, 1, 1, 2)
    # Baseline also flags 2004 (2 mm), which the engine passes thanks to wet soil.
    assert counts["baseline"] == (2, 1, 2, 1)
    assert all(row["n_seasons"] == 6 and row["n_elnino"] == 3 for row in rows)


def test_threshold_comes_from_params(monkeypatch: pytest.MonkeyPatch) -> None:
    weather, elnino = synthetic()
    monkeypatch.setattr(params, "ADEQUACY_THRESHOLD", 0.0)
    engine = next(row for row in hindcast.run(weather, [CROP], elnino) if row["method"] == "engine")
    assert engine["n_flagged"] == 0


def test_incomplete_season_is_skipped() -> None:
    weather, elnino = synthetic()
    del weather[date(2005, 11, 2)]
    rows = hindcast.run(weather, [CROP], elnino)
    assert {row["n_seasons"] for row in rows} == {5}


def test_elnino_labels_read_from_enso_table(tmp_path: Path) -> None:
    (tmp_path / "oni").mkdir()
    (tmp_path / "oni/enso_dry_seasons.csv").write_text(
        "dry_season_start_year,el_nino\n1982,1\n1983,0\n", encoding="utf-8"
    )
    assert load_enso(tmp_path) == {1982: True, 1983: False}


def test_no_complete_season_raises() -> None:
    _, elnino = synthetic()
    with pytest.raises(ValueError, match="No complete seasons"):
        hindcast.run({}, [CROP], elnino)


def test_season_at_the_mean_is_not_flagged() -> None:
    seasons = [Season(2000, 1.0, 1.0), Season(2001, 1.0, 2.0), Season(2002, 1.0, 3.0)]
    assert hindcast.baseline_flags(seasons) == {2000: True, 2001: False, 2002: False}


def test_results_are_written_and_deterministic(tmp_path: Path) -> None:
    weather, elnino = synthetic()
    rows = hindcast.run(weather, [CROP], elnino)
    hindcast.write_results(rows, tmp_path)
    first = [(tmp_path / name).read_bytes() for name in ("hindcast.csv", "hindcast.md")]
    hindcast.write_results(hindcast.run(weather, [CROP], elnino), tmp_path)
    assert first == [(tmp_path / name).read_bytes() for name in ("hindcast.csv", "hindcast.md")]
    with (tmp_path / "hindcast.csv").open(newline="") as handle:
        written = list(csv.DictReader(handle))
    assert [row["method"] for row in written] == ["engine", "baseline"]
    assert written[0]["hits"] == "2"
    text = (tmp_path / "hindcast.md").read_text(encoding="utf-8")
    assert "| mungbean | engine | 6 | 3 | 3 | 2 | 1 | 1 | 67% | 33% |" in text
    assert chr(0x2014) not in text
