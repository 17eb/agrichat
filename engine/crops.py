"""Load engine crops with relative water demand derived from their stage curves."""

from pathlib import Path

from engine.rotation import Crop
from pipeline.budget import kc_curve
from pipeline.build_indicators import DATA, read_csv
from pipeline.build_indicators import load_crops as load_budget_crops


def load_crops(data: Path = DATA) -> list[Crop]:
    """Sum daily Kc as relative demand, assuming equal daily ET0 across crops.

    This is a relative demand measure, not a water budget in mm. Stage lengths
    and reviewer Kc values are shared with the offline pipeline.
    """
    rows = {row["crop"]: row for row in read_csv(data / "crops/crops_engine.csv")}
    return [
        Crop(
            name=crop.name,
            is_legume=bool(int(rows[crop.name]["is_legume"])),
            seasonal_water_demand=sum(kc_curve(crop)),
            income_flag=(
                float(rows[crop.name]["income_flag"]) if rows[crop.name]["income_flag"] else None
            ),
        )
        for crop in load_budget_crops(data)
    ]
