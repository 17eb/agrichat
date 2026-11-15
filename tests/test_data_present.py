from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def test_handoff_data_present() -> None:
    for rel in (
        "power/power_daily_1981_2025.csv",
        "power/power_daily_2026.csv",
        "oni/enso_dry_seasons.csv",
        "crops/crops_engine.csv",
        "kb/kb_chunks.csv",
    ):
        assert (DATA / rel).is_file(), rel
