from copy import deepcopy
from dataclasses import replace
from datetime import date

import pytest

from engine import params
from engine.reason_codes import REASON_CODES
from engine.rotation import Crop, Indicator, Profile, recommend

PROFILE = Profile("BATAC", "rice", "ULAN", None, date(2026, 11, 15))
CROPS = (Crop("rice", False, 120), Crop("mungbean", True, 60), Crop("soybean", True, 100))


def indicator(adequate: int = 9, **changes: object) -> Indicator:
    return replace(Indicator(10, adequate, 5, 1, 0.0, 0.0, "BATAC", "11-01/11-30"), **changes)


def test_pure_deterministic_and_not_input_order_dependent() -> None:
    indicators = dict.fromkeys((crop.name for crop in CROPS), indicator())
    before = deepcopy((PROFILE, indicators, CROPS))
    result = recommend(PROFILE, indicators, CROPS, False)
    assert result == recommend(PROFILE, indicators, CROPS, False)
    assert result == recommend(PROFILE, indicators, CROPS[::-1], False)
    assert (PROFILE, indicators, CROPS) == before
    assert result.crops[0].name == "mungbean"


def test_scores_follow_all_four_components() -> None:
    crop = Crop("mungbean", True, 60, income_flag=0.8)
    result = recommend(
        replace(PROFILE, priority="KITA"),
        {crop.name: indicator(8, heat_freq=0.25, harvest_rain_freq=0.25)},
        [crop],
        False,
    )
    best = result.crops[0]
    assert best.total == pytest.approx(40 + 20 + 15 + 8)
    assert (best.rotation_benefit, best.timing_risk, best.farmer_priority) == (1, 0.75, 0.8)
    assert result.template == "T_PLANT"
    assert result.reasons == best.reason_codes
    assert set(best.reason_codes) == {"R_WATER_OK", "R_LEGUME", "R_HEAT", "R_HARVEST_RAIN"}


@pytest.mark.parametrize("last_crop,benefit", [("rice", 0), ("soybean", 0.5), (None, 0.5)])
def test_rice_never_gets_full_rotation_marks(last_crop: str | None, benefit: float) -> None:
    result = recommend(
        replace(PROFILE, last_crop=last_crop), {"rice": indicator()}, [CROPS[0]], False
    )
    assert result.crops[0].rotation_benefit == benefit
    assert ("R_SAME_CROP" in result.reasons) == (last_crop == "rice")


def test_missing_indicators_and_missing_season_counts_never_guess() -> None:
    assert recommend(PROFILE, {}, CROPS, False).template == "T_NO_DATA"
    assert recommend(PROFILE, {"rice": indicator(n_years=0)}, CROPS, False).template == "T_NO_DATA"
    assert recommend(PROFILE, {"rice": indicator(n_elnino=0)}, CROPS, True).template == "T_NO_DATA"
    assert (
        recommend(PROFILE, {"rice": indicator(barangay_code="OTHER")}, CROPS, False).template
        == "T_NO_DATA"
    )


def test_el_nino_uses_both_el_nino_counts_and_changes_ranking() -> None:
    indicators = {
        "rice": indicator(10, n_adequate_elnino=5),
        "mungbean": indicator(9, n_adequate_elnino=0),
    }
    normal = recommend(PROFILE, indicators, CROPS, False)
    el_nino = recommend(PROFILE, indicators, CROPS, True)
    assert normal.crops[0].name == "mungbean"
    assert el_nino.crops[0].name == "rice"
    assert el_nino.crops[0].water_reliability == 1
    assert (el_nino.crops[0].n_adequate, el_nino.crops[0].n_years) == (5, 5)
    assert "R_WATER_SHORT" in el_nino.crops[1].reason_codes


@pytest.mark.parametrize("priority,winner", [("TUBIG", "mungbean"), ("KITA", "soybean")])
def test_priority_changes_ranking(priority: str, winner: str) -> None:
    crops = (replace(CROPS[1], income_flag=0), replace(CROPS[2], income_flag=1))
    result = recommend(
        replace(PROFILE, priority=priority),
        dict.fromkeys((c.name for c in crops), indicator()),
        crops,
        False,
    )
    assert result.crops[0].name == winner
    assert result.crops[0].farmer_priority == 1
    assert result.crops[1].farmer_priority == 0
    assert (
        "R_LESS_WATER" in next(c for c in result.crops if c.name == "mungbean").reason_codes
    ) == (priority == "TUBIG")


@pytest.mark.parametrize(
    "adequate,template",
    [
        (39, "T_PLANT"),
        (40, "T_PLANT_BORDER"),
        (50, "T_PLANT_BORDER"),
        (60, "T_PLANT_BORDER"),
        (61, "T_PLANT"),
    ],
)
def test_borderline_water_inclusive(adequate: int, template: str) -> None:
    result = recommend(PROFILE, {"rice": indicator(adequate, n_years=100)}, [CROPS[0]], False)
    assert result.template == template
    assert len(result.crops) == 1
    if template == "T_PLANT_BORDER":
        assert result.reasons == ()


@pytest.mark.parametrize("adequate,borderline", [(80, True), (79, False)])
def test_borderline_score_gap_inclusive(adequate: int, borderline: bool) -> None:
    crops = [CROPS[1], CROPS[2]]
    result = recommend(
        PROFILE,
        {"mungbean": indicator(100, n_years=100), "soybean": indicator(adequate, n_years=100)},
        crops,
        False,
    )
    assert (result.template == "T_PLANT_BORDER") == borderline


@pytest.mark.parametrize(
    "day,open_window",
    [
        (date(2026, 10, 31), False),
        (date(2026, 11, 1), True),
        (date(2026, 11, 30), True),
        (date(2026, 12, 1), False),
    ],
)
def test_closed_sowing_window(day: date, open_window: bool) -> None:
    result = recommend(replace(PROFILE, sowing_date=day), {"rice": indicator()}, CROPS, False)
    assert (result.template != "T_NO_DATA") == open_window


def test_closed_candidate_filtered_and_cross_year_window() -> None:
    indicators = {"rice": indicator(sow_window="12-01/01-31"), "mungbean": indicator()}
    assert [c.name for c in recommend(PROFILE, indicators, CROPS, False).crops] == ["mungbean"]
    january = replace(PROFILE, sowing_date=date(2027, 1, 1))
    assert recommend(january, indicators, CROPS, False).crops[0].name == "rice"


def test_weights_are_read_from_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(params, "SCORING_WEIGHTS", dict.fromkeys(params.SCORING_WEIGHTS, 0))
    result = recommend(PROFILE, {"rice": indicator()}, [CROPS[0]], False)
    assert result.crops[0].total == 0


def test_reason_phrases_match_spec_and_fit_sms_character_set() -> None:
    assert REASON_CODES == {
        "R_WATER_OK": "sapat ang tubig sa karamihan ng nakaraang tag-araw",
        "R_WATER_SHORT": "madalas kulang ang tubig para dito",
        "R_LESS_WATER": "mas kaunti ang tubig na kailangan",
        "R_LEGUME": "tumutulong ito sa lupa pagkatapos ng palay",
        "R_SAME_CROP": "sunod-sunod na parehong tanim",
        "R_HEAT": "may panganib ng matinding init sa pamumulaklak",
        "R_HARVEST_RAIN": "may panganib ng malakas na ulan sa anihan",
    }
    for phrase in REASON_CODES.values():
        assert len(phrase) <= 150
        assert all(32 <= ord(char) <= 126 for char in phrase)


def test_priority_uses_supplied_water_demands() -> None:
    crops = [
        replace(CROPS[1], seasonal_water_demand=200),
        replace(CROPS[2], seasonal_water_demand=100),
    ]
    result = recommend(
        replace(PROFILE, priority="TUBIG"),
        dict.fromkeys((c.name for c in crops), indicator()),
        crops,
        False,
    )
    assert result.crops[0].name == "soybean"
    assert result.crops[0].farmer_priority == 1


def test_missing_income_flags_give_no_income_preference() -> None:
    result = recommend(
        replace(PROFILE, priority="KITA"),
        dict.fromkeys((c.name for c in CROPS), indicator()),
        CROPS,
        False,
    )
    assert all(crop.farmer_priority == 0 for crop in result.crops)


@pytest.mark.parametrize("heat,rain", [(0, 1), (1, 0), (0.3, 0.7), (0.7, 0.3)])
def test_timing_uses_larger_risk(heat: float, rain: float) -> None:
    result = recommend(
        PROFILE, {"rice": indicator(heat_freq=heat, harvest_rain_freq=rain)}, [CROPS[0]], False
    )
    assert result.crops[0].timing_risk == pytest.approx(1 - max(heat, rain))
    assert 0 <= result.crops[0].total <= 100
    assert set(result.crops[0].reason_codes) <= REASON_CODES.keys()


@pytest.mark.parametrize(
    "changes",
    [{"n_adequate": 11}, {"n_adequate": -1}, {"heat_freq": -0.1}, {"harvest_rain_freq": 1.1}],
)
def test_invalid_counts_or_frequencies_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        recommend(PROFILE, {"rice": indicator(**changes)}, CROPS, False)


@pytest.mark.parametrize("priority", [None, "KITA"])
def test_real_data_reasons_explain_water_and_rotation(priority: str | None) -> None:
    from engine.crops import load_crops
    from pipeline.build_indicators import DATA, read_csv

    indicators = {
        row["crop"]: Indicator(
            n_years=int(row["n_years"]),
            n_adequate=int(row["n_adequate"]),
            n_elnino=int(row["n_elnino"]),
            n_adequate_elnino=int(row["n_adequate_elnino"]),
            heat_freq=float(row["heat_freq"]),
            harvest_rain_freq=float(row["harvest_rain_freq"]),
            barangay_code=row["barangay_code"],
            sow_window=row["sow_window"],
        )
        for row in read_csv(DATA / "indicators.csv")
    }
    result = recommend(replace(PROFILE, priority=priority), indicators, load_crops(), False)
    assert result.crops[0].name == "mungbean"
    assert result.crops[0].reason_codes[:2] == ("R_WATER_OK", "R_LEGUME")
    assert all("R_LESS_WATER" not in crop.reason_codes for crop in result.crops)


def test_reasons_sort_by_weighted_component_contribution() -> None:
    result = recommend(PROFILE, {"mungbean": indicator(1, heat_freq=0.3)}, [CROPS[1]], False)
    assert result.crops[0].reason_codes == ("R_LEGUME", "R_HEAT", "R_WATER_SHORT")


def test_reason_contribution_ties_preserve_fixed_order() -> None:
    result = recommend(PROFILE, {"mungbean": indicator(4, heat_freq=0.3)}, [CROPS[1]], False)
    assert result.crops[0].reason_codes == ("R_WATER_SHORT", "R_LEGUME", "R_HEAT")


@pytest.mark.parametrize("priority", [None, "KITA", "TUBIG"])
def test_crop_outside_original_demand_dictionary_can_be_ranked(priority: str | None) -> None:
    crop = Crop("corn", False, 90, income_flag=0.5)
    result = recommend(replace(PROFILE, priority=priority), {"corn": indicator()}, [crop], False)
    assert result.template == "T_PLANT"
    assert result.crops[0].name == "corn"
    assert 0 <= result.crops[0].total <= 100


def test_unused_demands_do_not_get_evaluated() -> None:
    crop = Crop("corn", False, 0)
    assert recommend(PROFILE, {"corn": indicator()}, [crop], False).template == "T_PLANT"
    with pytest.raises(ValueError, match="demand"):
        recommend(replace(PROFILE, priority="TUBIG"), {"corn": indicator()}, [crop], False)


def test_crop_loader_derives_demand_from_pipeline_stage_curves() -> None:
    from engine.crops import load_crops
    from pipeline.budget import kc_curve
    from pipeline.build_indicators import load_crops as load_budget_crops

    crops = {crop.name: crop for crop in load_crops()}
    assert set(crops) == {"rice", "mungbean", "soybean"}
    for crop in load_budget_crops():
        assert crops[crop.name].seasonal_water_demand == pytest.approx(sum(kc_curve(crop)))
        assert crops[crop.name].income_flag is None
    assert crops["mungbean"].is_legume
    assert not crops["rice"].is_legume


@pytest.mark.parametrize("frequency,reported", [(0.199, False), (0.2, False), (0.201, True)])
def test_timing_reasons_require_meaningful_frequency(frequency: float, reported: bool) -> None:
    result = recommend(
        PROFILE,
        {"rice": indicator(heat_freq=frequency, harvest_rain_freq=frequency)},
        [CROPS[0]],
        False,
    )
    assert ("R_HEAT" in result.crops[0].reason_codes) == reported
    assert ("R_HARVEST_RAIN" in result.crops[0].reason_codes) == reported


def test_indicator_requires_location_and_sowing_window() -> None:
    with pytest.raises(TypeError):
        Indicator(10, 9, 5, 1, 0, 0)


def test_float_noise_does_not_break_inclusive_borderline_gap() -> None:
    result = recommend(
        PROFILE,
        {"mungbean": indicator(10), "soybean": indicator(8, heat_freq=1e-12)},
        CROPS,
        False,
    )
    assert [crop.total for crop in result.crops] == [90, 80]
    assert result.template == "T_PLANT_BORDER"


def test_float_noise_does_not_change_tie_break_order() -> None:
    result = recommend(
        PROFILE,
        {"mungbean": indicator(9, heat_freq=1e-12), "soybean": indicator(9)},
        CROPS,
        False,
    )
    assert result.crops[0].total == result.crops[1].total == 85
    assert [crop.name for crop in result.crops] == ["mungbean", "soybean"]


def test_missing_indicator_drops_only_that_crop() -> None:
    result = recommend(PROFILE, {"rice": indicator(10), "mungbean": indicator(9)}, CROPS, False)
    assert result.template != "T_NO_DATA"
    assert [crop.name for crop in result.crops] == ["mungbean", "rice"]
