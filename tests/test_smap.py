"""Offline AppEEARS acquisition, processing and record checks."""

import csv
import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import requests

from scripts import check_smap, fetch_smap

FIXTURE = Path(__file__).parent / "fixtures/smap_results.csv"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Network calls are forbidden in SMAP tests")

    monkeypatch.setattr(requests.sessions.Session, "request", reject)


def product_layers(optional: bool = True) -> dict[str, Any]:
    names = list(fetch_smap.VARIABLES.values())[: 4 if optional else 3]
    return {
        "Geophysical_Data_" + name: {
            "FillValue": -9999,
            "Units": "percent" if "percentile" in name else "fraction",
            "ValidMin": 0,
            "ValidMax": 100 if "percentile" in name else 1,
            "Available": True,
            "IsQA": False,
        }
        for name in names
    }


class Response:
    def __init__(self, payload: Any = None, content: bytes = b"") -> None:
        self.payload = payload
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [self.content]

    def close(self) -> None:
        return None


class Session:
    def __init__(self, statuses: list[str] | None = None) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.statuses = list(statuses or ["pending", "done"])
        self.seconds = 0.0
        self.sleeps: list[float] = []

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.seconds += seconds

    def clock(self) -> float:
        return self.seconds

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        path = url.removeprefix(fetch_smap.API)
        self.calls.append((method, path, kwargs))
        assert kwargs["timeout"] == 30
        if path == "/login":
            assert "Authorization" not in self.headers
            return Response({"token": "synthetic-token"})
        assert self.headers["Authorization"] == "Bearer synthetic-token"
        assert "auth" not in kwargs
        if path == "/logout":
            return Response()
        if path.startswith("/product/"):
            assert path == "/product/SPL4SMGP.008"
            return Response(product_layers())
        if path == "/task":
            return Response({"task_id": "synthetic-task"})
        if path == "/task/synthetic-task":
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return Response({"status": status})
        if path == "/bundle/synthetic-task":
            return Response(
                {
                    "files": [
                        {"file_name": "point-results.csv", "file_id": "results"},
                        {"file_name": "point-metadata.xml", "file_id": "metadata"},
                    ]
                }
            )
        if path.endswith("/results"):
            return Response(content=FIXTURE.read_bytes())
        if path.endswith("/metadata"):
            return Response(content=b"<metadata>synthetic</metadata>")
        raise AssertionError(f"Unexpected request: {method} {path}")


def test_complete_point_flow_and_retained_bundle(tmp_path: Path) -> None:
    session = Session()
    task, layers, paths = fetch_smap.AppEEARS(session, session.sleep, session.clock).download(
        "synthetic",
        "synthetic",
        tmp_path,
        date(2026, 11, 15),
        18.06,
        120.56,
    )
    assert task == "synthetic-task"
    assert len(layers) == 4
    assert {p.name for p in paths} == {"point-results.csv", "point-metadata.xml"}
    assert paths[0].read_bytes() == FIXTURE.read_bytes()
    assert session.sleeps == [60, 60]
    assert session.calls[-1][0:2] == ("POST", "/logout")
    assert "Authorization" not in session.headers
    payload = json.loads((tmp_path / "request.json").read_text())
    assert payload["task_type"] == "point"
    assert payload["params"]["dates"] == [{"startDate": "03-31-2015", "endDate": "11-15-2026"}]
    assert payload["params"]["coordinates"][0]["latitude"] == 18.06
    assert payload["params"]["layers"] == [
        {"product": "SPL4SMGP.008", "layer": layer} for layer, _ in layers.values()
    ]
    assert json.loads((tmp_path / "product_layers.json").read_text()) == product_layers()
    assert "synthetic-token" not in "".join(p.read_text() for p in tmp_path.iterdir())


@pytest.mark.parametrize("status,exception", [("pending", TimeoutError), ("error", ValueError)])
def test_poll_cap_and_failure_always_logout(tmp_path: Path, status: str, exception: type) -> None:
    session = Session([status])
    with pytest.raises(exception):
        fetch_smap.AppEEARS(session, session.sleep, session.clock).download(
            "synthetic",
            "synthetic",
            tmp_path,
            date(2026, 1, 1),
            18.06,
            120.56,
        )
    assert session.calls[-1][1] == "/logout"
    assert session.seconds <= 10800
    assert all(seconds == 60 for seconds in session.sleeps)


def test_layer_selection_requires_advertised_unique_layers() -> None:
    product = product_layers(optional=False)
    layers = fetch_smap.select_layers(product)
    assert len(layers) == 3
    product["other_sm_rootzone"] = product["Geophysical_Data_sm_rootzone"]
    with pytest.raises(ValueError, match="one advertised"):
        fetch_smap.select_layers(product)
    with pytest.raises(ValueError, match="one advertised"):
        fetch_smap.select_layers({})


def test_daily_pht_fill_and_percentile() -> None:
    rows, pixel = fetch_smap.daily_means(
        [FIXTURE],
        fetch_smap.select_layers(product_layers()),
        "BATAC",
    )
    assert pixel == ("18.1", "120.6")
    assert rows[0]["date"] == "2015-03-31"
    assert rows[0]["sm_rootzone_m3m3"] == pytest.approx(0.2)
    assert rows[0]["sm_surface_m3m3"] == 0.05
    assert rows[0]["n_obs"] == 2
    assert rows[1]["date"] == "2015-04-01"
    assert rows[1]["sm_rootzone_m3m3"] == 0.6
    assert rows[1]["n_obs"] == 1
    assert rows[-1]["soilwet_pct"] == pytest.approx(100 / 3)
    assert rows[-1]["sm_rootzone_pctl_product"] == 30


def test_percentile_window_inclusive_excludes_same_year_and_wraps() -> None:
    rows = [
        {"date": day, "sm_rootzone_m3m3": value}
        for day, value in [
            ("2018-01-01", 0.3),
            ("2017-01-16", 0.2),
            ("2017-01-17", 0.8),
            ("2017-12-31", 0.4),
            ("2018-01-02", 0.5),
            ("2016-01-01", None),
        ]
    ]
    baseline = fetch_smap.baseline_rows(date(2018, 1, 1), rows)
    assert {row["date"] for row in baseline} == {"2017-01-16", "2017-12-31"}


def test_duplicate_observations_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        fetch_smap.daily_means(
            [FIXTURE, FIXTURE], fetch_smap.select_layers(product_layers()), "BATAC"
        )


def test_writes_all_outputs_and_power_comparison(tmp_path: Path) -> None:
    power = tmp_path / "power"
    power.mkdir()
    (power / "power_daily_1981_2025.csv").write_text(
        "barangay_code,date,gwetroot\nBATAC,2015-03-31,0.1\nBATAC,2015-04-01,0.6\n"
        "BATAC,2017-03-31,0.2\nOTHER,2017-03-31,0.9\n"
    )
    fetch_smap.process_results(
        [FIXTURE],
        fetch_smap.select_layers(product_layers()),
        "synthetic-task",
        tmp_path,
        "BATAC",
        datetime(2017, 3, 31, 16, tzinfo=UTC),
    )
    output = tmp_path / "smap"
    assert {path.name for path in output.iterdir()} == {
        "smap_l4_daily.csv",
        "smap_now.csv",
        "smap_vs_power.csv",
        "smap_metadata.csv",
    }
    daily = fetch_smap.read_csv(output / "smap_l4_daily.csv")
    assert tuple(daily[0]) == fetch_smap.DAILY_FIELDS
    now = fetch_smap.read_csv(output / "smap_now.csv")[0]
    assert tuple(now) == fetch_smap.NOW_FIELDS
    assert now["latest_date"] == "2017-03-31"
    assert now["days_since_latest"] == "1"
    assert now["years_in_baseline"] == "2"
    metadata = fetch_smap.read_csv(output / "smap_metadata.csv")
    assert len(metadata) == 4
    assert metadata[0]["task_id"] == "synthetic-task"
    assert metadata[0]["pixel_lat"] == "18.1"
    assert "2019" in metadata[0]["notes"]
    comparison = fetch_smap.read_csv(output / "smap_vs_power.csv")[0]
    assert comparison["n_days"] == "3"
    assert float(comparison["mean_diff"]) == pytest.approx(0.2)
    assert float(comparison["pearson_r"]) == pytest.approx(1)


def test_optional_layer_and_no_power(tmp_path: Path) -> None:
    fetch_smap.process_results(
        [FIXTURE],
        fetch_smap.select_layers(product_layers(optional=False)),
        "synthetic-task",
        tmp_path,
        "BATAC",
        datetime(2017, 4, 1, tzinfo=UTC),
    )
    rows = fetch_smap.read_csv(tmp_path / "smap/smap_l4_daily.csv")
    assert all(row["sm_rootzone_pctl_product"] == "" for row in rows)
    comparison = fetch_smap.read_csv(tmp_path / "smap/smap_vs_power.csv")[0]
    assert comparison == {
        "n_days": "0",
        "pearson_r": "",
        "mean_diff": "",
        "note": "POWER file absent",
    }


def test_all_fill_day_has_blank_means_and_no_baseline(tmp_path: Path) -> None:
    path = tmp_path / "point-results.csv"
    lines = FIXTURE.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[4]]) + "\n")
    rows, _ = fetch_smap.daily_means(
        [path],
        fetch_smap.select_layers(product_layers()),
        "BATAC",
    )
    assert rows[0]["date"] == "2015-04-01"
    assert rows[0]["sm_rootzone_m3m3"] is None
    assert rows[0]["n_obs"] == 0
    assert rows[0]["soilwet_pct"] is None
    with pytest.raises(ValueError, match="no valid root-zone"):
        fetch_smap.process_results(
            [path],
            fetch_smap.select_layers(product_layers()),
            "synthetic-task",
            tmp_path,
            "BATAC",
            datetime(2015, 4, 1, tzinfo=UTC),
        )


def test_fetch_main_with_fake_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pilot = tmp_path / "barangays"
    pilot.mkdir()
    (pilot / "barangays.csv").write_text("barangay_code,lat,lon\nBATAC,18.06,120.56\n")
    session = Session()
    client_class = fetch_smap.AppEEARS
    monkeypatch.setattr(fetch_smap, "DATA", tmp_path)
    monkeypatch.setenv("EARTHDATA_USER", "synthetic")
    monkeypatch.setenv("EARTHDATA_PASS", "synthetic")
    monkeypatch.setattr(fetch_smap.requests, "Session", lambda: session)
    monkeypatch.setattr(
        fetch_smap,
        "AppEEARS",
        lambda client: client_class(client, session.sleep, session.clock),
    )
    assert fetch_smap.main([]) == 0
    assert session.calls[0][2]["auth"] == ("synthetic", "synthetic")
    assert (tmp_path / "smap/smap_now.csv").exists()
    assert "synthetic" not in str(capsys.readouterr())


def test_fetch_failure_does_not_print_http_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pilot = tmp_path / "barangays"
    pilot.mkdir()
    (pilot / "barangays.csv").write_text("barangay_code,lat,lon\nBATAC,18.06,120.56\n")
    session = Session()

    def fail_request(*args: Any, **kwargs: Any) -> None:
        raise requests.HTTPError("synthetic sensitive server response")

    monkeypatch.setattr(session, "request", fail_request)
    monkeypatch.setattr(fetch_smap.requests, "Session", lambda: session)
    monkeypatch.setattr(fetch_smap, "DATA", tmp_path)
    monkeypatch.setenv("EARTHDATA_USER", "synthetic")
    monkeypatch.setenv("EARTHDATA_PASS", "synthetic")
    assert fetch_smap.main([]) == 1
    output = capsys.readouterr()
    assert "synthetic" not in output.err
    assert "SMAP fetch failed" in output.err


@pytest.mark.parametrize("missing", ["EARTHDATA_USER", "EARTHDATA_PASS", "both"])
def test_missing_credentials_exit_two_without_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    monkeypatch.setenv("EARTHDATA_USER", "synthetic")
    monkeypatch.setenv("EARTHDATA_PASS", "synthetic")
    for name in ("EARTHDATA_USER", "EARTHDATA_PASS") if missing == "both" else (missing,):
        monkeypatch.delenv(name)

    def reject() -> None:
        pytest.fail("No session may be created without credentials")

    monkeypatch.setattr(fetch_smap.requests, "Session", reject)
    assert fetch_smap.main([]) == 2
    assert "EARTHDATA_USER and EARTHDATA_PASS" in capsys.readouterr().err


def good_rows() -> list[dict[str, str]]:
    rows = []
    day = check_smap.START
    while day <= date(2015, 9, 30):
        rows.append(
            {
                "barangay_code": "BATAC",
                "date": day.isoformat(),
                "sm_rootzone_m3m3": "0.1" if day.month < 7 else "0.5",
                "sm_surface_m3m3": "0.1",
                "sm_rootzone_wetness": "0.5",
                "sm_rootzone_pctl_product": "",
                "soilwet_pct": "",
                "n_obs": "8",
            }
        )
        day += timedelta(days=1)
    return rows


def test_checks_pass_and_report_lag_and_observation_share() -> None:
    errors, reports = check_smap.check_rows(good_rows(), date(2015, 10, 7))
    assert errors == []
    assert "Missing days: 0" in reports
    assert any("(0.0%)" in report for report in reports)
    assert "Latest SMAP data lag at fetch (2015-10-07 PHT): 7 days" in reports


@pytest.mark.parametrize(
    "problem, expected",
    [
        ("gap", "missing days"),
        ("start", "begin"),
        ("root", "sm_rootzone_m3m3"),
        ("surface", "sm_surface_m3m3"),
        ("wetness", "sm_rootzone_wetness"),
        ("observations", "Most SMAP"),
        ("seasons", "drier"),
        ("stale", "last 7 days"),
        ("future", "last 7 days"),
        ("duplicate", "Duplicate"),
        ("percentile", "soilwet_pct"),
    ],
)
def test_spec_checks_detect_failures(problem: str, expected: str) -> None:
    rows = good_rows()
    today = date(2015, 9, 30)
    if problem == "gap":
        rows.pop(10)
    elif problem == "start":
        rows.pop(0)
    elif problem in {"root", "surface", "wetness"}:
        key = {
            "root": "sm_rootzone_m3m3",
            "surface": "sm_surface_m3m3",
            "wetness": "sm_rootzone_wetness",
        }[problem]
        rows[0][key] = "nan" if problem == "root" else "1.1"
    elif problem in {"observations", "seasons"}:
        for row in rows:
            row["n_obs" if problem == "observations" else "sm_rootzone_m3m3"] = (
                "7" if problem == "observations" else "0.5"
            )
    elif problem == "stale":
        today += timedelta(days=8)
    elif problem == "future":
        today -= timedelta(days=1)
    elif problem == "duplicate":
        rows.append(rows[-1])
    elif problem == "percentile":
        rows[0]["soilwet_pct"] = "101"
    errors, reports = check_smap.check_rows(rows, today)
    assert any(expected in error for error in errors)
    if problem == "gap":
        assert "Missing days: 1: 2015-04-10" in reports


def test_check_cli_nonzero_for_missing_empty_and_malformed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "daily.csv"
    monkeypatch.setattr(check_smap, "DATA", path)
    assert check_smap.main() == 1
    path.write_text("date\n")
    assert check_smap.main() == 1
    path.write_text("date\ninvalid\n")
    assert check_smap.main() == 1


def test_check_cli_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = good_rows()
    path = tmp_path / "daily.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(check_smap, "DATA", path)

    (tmp_path / "smap_metadata.csv").write_text("accessed_utc\n2015-09-30T16:00:00Z\n")
    assert check_smap.main() == 0


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        "accessed_utc\n",
        "wrong_column\n2015-09-30\n",
        "accessed_utc\ninvalid\n",
        "accessed_utc\n2015-09-30T00:00:00\n",
        "accessed_utc\n2015-10-08T00:00:00Z\n",
        "accessed_utc\n2015-10-07T16:00:00Z\n",
    ],
)
def test_check_cli_requires_valid_fetch_metadata_and_fresh_at_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metadata: str | None,
) -> None:
    rows = good_rows()
    path = tmp_path / "daily.csv"
    fetch_smap.write_csv(path, tuple(rows[0]), rows)
    monkeypatch.setattr(check_smap, "DATA", path)
    if metadata is not None:
        (tmp_path / "smap_metadata.csv").write_text(metadata)
    assert check_smap.main() == 1


def test_check_reports_all_fill_day_as_gap_not_range_error() -> None:
    rows = good_rows()
    for key in ("sm_rootzone_m3m3", "sm_surface_m3m3", "sm_rootzone_wetness"):
        rows[10][key] = ""
    rows[10]["n_obs"] = "0"
    errors, reports = check_smap.check_rows(rows, date(2015, 9, 30))
    assert "SMAP record has missing days" in errors
    assert "Missing days: 1: 2015-04-10" in reports
    assert not any("between" in error for error in errors)


def test_reprocess_downloaded_raw_without_network_or_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = tmp_path / "downloaded"
    session = Session(["done"])
    fetch_smap.AppEEARS(session, session.sleep, session.clock).download(
        "synthetic",
        "synthetic",
        raw,
        date(2026, 11, 15),
        18.06,
        120.56,
    )
    accessed = json.loads((raw / "task.json").read_text())["accessed_utc"]
    first = tmp_path / "first"
    fetch_smap.process_raw(raw, first, "BATAC", datetime(2050, 1, 1, tzinfo=UTC))
    data = tmp_path / "reprocessed"
    shutil.copytree(raw, data / "smap/raw")
    monkeypatch.setattr(fetch_smap, "DATA", data)
    monkeypatch.delenv("EARTHDATA_USER", raising=False)
    monkeypatch.delenv("EARTHDATA_PASS", raising=False)

    def reject() -> None:
        pytest.fail("Process-only must not create an HTTP session")

    monkeypatch.setattr(fetch_smap.requests, "Session", reject)
    assert fetch_smap.main(["--process-only"]) == 0
    for name in ("smap_l4_daily.csv", "smap_now.csv", "smap_vs_power.csv", "smap_metadata.csv"):
        assert (first / "smap" / name).read_bytes() == (data / "smap" / name).read_bytes()
    assert fetch_smap.read_csv(data / "smap/smap_metadata.csv")[0]["accessed_utc"] == accessed


def test_logout_transport_error_warns_without_discarding_download(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class LogoutFailureSession(Session):
        def request(self, method: str, url: str, **kwargs: Any) -> Response:
            if url.endswith("/logout"):
                raise requests.ConnectionError("sensitive server body")
            return super().request(method, url, **kwargs)

    session = LogoutFailureSession(["done"])
    task_id, _, paths = fetch_smap.AppEEARS(session, session.sleep, session.clock).download(
        "synthetic",
        "synthetic",
        tmp_path,
        date(2026, 1, 1),
        18.06,
        120.56,
    )
    assert task_id == "synthetic-task"
    assert len(paths) == 2
    assert "Authorization" not in session.headers
    warning = capsys.readouterr().err
    assert "logout failed" in warning
    assert "sensitive" not in warning


@pytest.mark.parametrize("failures", [1, 3])
def test_status_transport_retries_are_bounded(tmp_path: Path, failures: int) -> None:
    class PollFailureSession(Session):
        def __init__(self) -> None:
            super().__init__(["done"])
            self.attempts = 0

        def request(self, method: str, url: str, **kwargs: Any) -> Response:
            if url.endswith("/task/synthetic-task"):
                self.attempts += 1
                if self.attempts <= failures:
                    raise requests.ConnectionError("sensitive transport detail")
            return super().request(method, url, **kwargs)

    session = PollFailureSession()
    client = fetch_smap.AppEEARS(session, session.sleep, session.clock)
    if failures == 1:
        assert (
            client.download(
                "synthetic",
                "synthetic",
                tmp_path,
                date(2026, 1, 1),
                18.06,
                120.56,
            )[0]
            == "synthetic-task"
        )
        assert session.attempts == 2
    else:
        with pytest.raises(requests.ConnectionError):
            client.download(
                "synthetic",
                "synthetic",
                tmp_path,
                date(2026, 1, 1),
                18.06,
                120.56,
            )
        assert session.attempts == 3
    assert session.calls[-1][1] == "/logout"
    assert session.sleeps == [60] * session.attempts


def test_retry_wait_respects_remaining_deadline() -> None:
    session = Session()
    client = fetch_smap.AppEEARS(session, session.sleep, session.clock)
    with pytest.raises(TimeoutError):
        client.poll("synthetic-task", 60)
    assert session.seconds <= 60
    assert session.calls == []


@pytest.mark.parametrize(
    "day,included,excluded",
    [
        (date(2018, 1, 1), "2017-12-17", "2017-12-16"),
        (date(2018, 12, 31), "2017-01-15", "2017-01-16"),
        (date(2016, 3, 1), "2017-02-14", "2017-02-13"),
        (date(2017, 3, 1), "2016-02-15", "2016-02-14"),
        (date(2016, 2, 29), "2017-02-13", "2017-02-12"),
    ],
)
def test_calendar_window_year_end_and_leap_boundaries(
    day: date,
    included: str,
    excluded: str,
) -> None:
    rows = [{"date": value, "sm_rootzone_m3m3": 0.5} for value in (included, excluded)]
    assert [row["date"] for row in fetch_smap.baseline_rows(day, rows)] == [included]


def test_failure_diagnostic_has_step_status_and_retained_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class DownloadFailureSession(Session):
        def request(self, method: str, url: str, **kwargs: Any) -> Response:
            if url.endswith("/results"):
                response = requests.Response()
                response.status_code = 503
                raise requests.HTTPError("sensitive body and ?secret=value", response=response)
            return super().request(method, url, **kwargs)

    session = DownloadFailureSession(["done"])
    pilot = tmp_path / "barangays"
    pilot.mkdir()
    (pilot / "barangays.csv").write_text("barangay_code,lat,lon\nBATAC,18.06,120.56\n")
    client_class = fetch_smap.AppEEARS
    monkeypatch.setattr(fetch_smap, "DATA", tmp_path)
    monkeypatch.setenv("EARTHDATA_USER", "synthetic")
    monkeypatch.setenv("EARTHDATA_PASS", "synthetic")
    monkeypatch.setattr(fetch_smap.requests, "Session", lambda: session)
    monkeypatch.setattr(
        fetch_smap,
        "AppEEARS",
        lambda client: client_class(client, session.sleep, session.clock),
    )
    assert fetch_smap.main([]) == 1
    error = capsys.readouterr().err
    assert "bundle download (HTTPError; HTTP 503)" in error
    assert str(tmp_path / "smap/raw/task.json") in error
    assert "sensitive" not in error
    assert "secret" not in error
