import hashlib
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import DATA
from app.main import create_app
from app.templates import PLAIN_TEMPLATES, TEMPLATES, WEAK_RETRIEVAL_TEMPLATE, render
from web.public import SENDER_PATTERN, STATIC, client_address, water_summary
from web.ratelimit import RateLimiter
from web.translate import ENGLISH, english_gloss

SENDER = "sim-" + "ab" * 16


def make_settings(tmp_path: Path, secret: bool = True) -> Settings:
    return Settings(
        db_path=str(tmp_path / "web.sqlite3"),
        phone_hash_secret=hashlib.sha256(b"web-fixture-material").hexdigest() if secret else "",
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(tmp_path))) as test_client:
        yield test_client


def post(client: TestClient, text: str, sender: str = SENDER, **kwargs: object):
    return client.post("/simulate", json={"from": sender, "text": text}, **kwargs)


def test_home_page_renders(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "<h1>" in html
    assert 'id="sim-form"' in html
    assert 'id="water-chart"' in html
    assert 'id="sim-steps"' in html
    assert "/static/site.css" in html
    assert "/static/public.css" in html
    assert "/static/simulator.js" in html
    assert re.search(r'<label [^>]*for="sim-input"', html)
    assert 'name="viewport"' in html


def test_home_loads_no_third_party_script(client: TestClient) -> None:
    html = client.get("/").text
    assert re.findall(r'<script src="([^"]+)"', html) == ["/static/simulator.js"]


def test_home_chart_is_server_rendered_from_indicators(client: TestClient) -> None:
    summary = water_summary(client.app.state.settings.db_path)
    assert [item["crop"] for item in summary] == ["rice", "mungbean", "soybean"]
    html = client.get("/").text
    for item in summary:
        assert f"{item['normal']} of {item['normal_total']} ({item['normal_pct']}%)" in html
        assert f"{item['elnino']} of {item['elnino_total']} ({item['elnino_pct']}%)" in html
    best = max(summary, key=lambda item: item["elnino_pct"])
    assert f"{best['label'].lower()} holds up" in html


def test_wordmark_shown_until_logo_exists(client: TestClient) -> None:
    assert not (STATIC / "img" / "logo.png").exists()
    html = client.get("/").text
    assert 'class="wordmark"' in html
    assert "logo.png" not in html


def test_data_page_renders_spec_content(client: TestClient) -> None:
    response = client.get("/data")
    assert response.status_code == 200
    html = response.text
    for needle in (
        "NASA POWER",
        "NASA SMAP Level 4",
        "SMAP versus POWER",
        "Oceanic Niño Index",
        "Limits",
        "How AI is used",
        "github.com/17eb/agrichat",
        "municipality scale",
    ):
        assert needle in html
    assert "The SMAP comparison is not available yet" in html


def test_data_page_shows_smap_comparison_when_present(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    comparison = tmp_path / "smap_vs_power.csv"
    comparison.write_text("metric,value\ncorrelation,0.81\n")
    monkeypatch.setattr("web.public.SMAP_VS_POWER", comparison)
    html = client.get("/data").text
    assert "correlation" in html
    assert "0.81" in html
    assert "not available yet" not in html


def test_static_assets_served(client: TestClient) -> None:
    css = client.get("/static/site.css")
    assert css.status_code == 200
    assert "--deep-green" in css.text
    assert "prefers-color-scheme: dark" in css.text
    assert client.get("/static/simulator.js").status_code == 200


def test_pages_have_no_long_dash() -> None:
    for path in [*STATIC.glob("*"), *(STATIC.parent / "templates").rglob("*.html")]:
        assert chr(0x2014) not in path.read_text()


def test_ui_pages_list() -> None:
    lines = (DATA.parent / "tools/ui_pages.txt").read_text().split()
    assert lines == ["/", "/data", "/admin/login"]


def test_simulate_runs_the_sms_handler(client: TestClient) -> None:
    help_reply = post(client, "HELP")
    assert help_reply.status_code == 200
    body = help_reply.json()
    assert body["template_id"] == "T_HELP"
    assert body["reply"] == render("T_HELP").text
    assert body["length"] == len(body["reply"])
    assert body["translation"].startswith("AgriChat: REG")

    registered = post(client, "REG BATAC ULAN").json()
    assert registered["template_id"] == "T_REG_OK"
    assert "Brgy Batac" in registered["reply"]
    assert registered["translation"] == (
        "You are registered in Brgy Batac, rain-fed. Text LAST and your last crop. Ex: LAST PALAY"
    )
    assert post(client, "LAST PALAY").json()["template_id"] == "T_LAST_OK"
    plant = post(client, "PLANT").json()
    assert plant["template_id"] in {"T_PLANT", "T_PLANT_BORDER"}
    assert plant["length"] == len(plant["reply"]) <= 150
    assert plant["translation"]


def test_simulate_unknown_text_falls_back_with_translation(client: TestClient) -> None:
    body = post(client, "asdf qwer").json()
    assert body["template_id"] == "T_FALLBACK"
    assert body["translation"] == "I did not understand. Text HELP for the list of commands."


def test_simulate_sends_no_sms_and_stores_hash_only(client: TestClient, tmp_path: Path) -> None:
    post(client, "REG BATAC ULAN")
    with sqlite3.connect(tmp_path / "web.sqlite3") as connection:
        stored = [row[0] for row in connection.execute("SELECT phone_hash FROM farmers")]
    assert len(stored) == 1
    assert SENDER not in stored[0]
    assert re.fullmatch(r"[0-9a-f]{64}", stored[0])


@pytest.mark.parametrize(
    "payload",
    [
        {"from": "+639123456789", "text": "HELP"},
        {"from": "09123456789", "text": "HELP"},
        {"from": "sim-short", "text": "HELP"},
        {"from": SENDER, "text": ""},
        {"from": SENDER, "text": "x" * 501},
        {"text": "HELP"},
        {"from": SENDER},
    ],
)
def test_simulate_rejects_bad_body(client: TestClient, payload: dict[str, str]) -> None:
    assert client.post("/simulate", json=payload).status_code == 422


def test_sender_pattern_never_matches_a_phone_number() -> None:
    assert re.fullmatch(SENDER_PATTERN, SENDER)
    assert not re.fullmatch(SENDER_PATTERN, "+639123456789")


def test_simulate_without_hash_secret_is_unavailable(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path, secret=False))) as bare:
        response = post(bare, "HELP")
    assert response.status_code == 503


def test_simulate_is_rate_limited_per_ip(tmp_path: Path) -> None:
    application = create_app(make_settings(tmp_path))
    application.state.simulate_limiter = RateLimiter(3, 60)
    with TestClient(application, client=("127.0.0.1", 50000)) as client:
        check_rate_limit(client)


def check_rate_limit(client: TestClient) -> None:
    for _ in range(3):
        assert post(client, "HELP", headers={"x-forwarded-for": "203.0.113.5"}).status_code == 200
    blocked = post(client, "HELP", headers={"x-forwarded-for": "203.0.113.5"})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    assert "Too many" in blocked.json()["detail"]
    other = post(client, "HELP", headers={"x-forwarded-for": "203.0.113.6"})
    assert other.status_code == 200


def test_default_rate_limit_allows_normal_use_then_blocks(client: TestClient) -> None:
    from web.public import SIMULATE_LIMIT

    statuses = [post(client, "HELP").status_code for _ in range(SIMULATE_LIMIT + 1)]
    assert statuses[:SIMULATE_LIMIT] == [200] * SIMULATE_LIMIT
    assert statuses[-1] == 429


def test_rate_limiter_window_and_prune() -> None:
    now = [0.0]
    limiter = RateLimiter(2, 10, clock=lambda: now[0])
    assert limiter.allow("a")
    assert limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.retry_after("a") == 11
    now[0] = 10.5
    assert limiter.allow("a")
    now[0] = 100.0
    assert limiter.allow("b")
    assert "a" not in limiter._hits
    assert limiter.retry_after("a") == 0


def test_client_address_trusts_forwarded_only_from_loopback() -> None:
    class Stub:
        def __init__(self, host: str, forwarded: str) -> None:
            self.client = type("Client", (), {"host": host})()
            self.headers = {"x-forwarded-for": forwarded} if forwarded else {}

    assert client_address(Stub("127.0.0.1", "198.51.100.1, 203.0.113.9")) == "203.0.113.9"  # type: ignore[arg-type]
    assert client_address(Stub("198.51.100.7", "203.0.113.9")) == "198.51.100.7"  # type: ignore[arg-type]
    assert client_address(Stub("127.0.0.1", "")) == "127.0.0.1"  # type: ignore[arg-type]


def test_indicators_json(client: TestClient) -> None:
    response = client.get("/indicators/BATAC")
    assert response.status_code == 200
    rows = response.json()
    assert {row["crop"] for row in rows} == {"rice", "mungbean", "soybean"}
    rice = next(row for row in rows if row["crop"] == "rice")
    assert rice["n_years"] == 45
    assert rice["n_elnino"] == 15
    assert 0 <= rice["n_adequate_elnino"] <= rice["n_elnino"]
    assert client.get("/indicators/batac").json() == rows


@pytest.mark.parametrize("code", ["NOWHERE", "bad%20code", "x" * 40])
def test_indicators_unknown_code_is_404(client: TestClient, code: str) -> None:
    assert client.get(f"/indicators/{code}").status_code == 404


def test_every_filipino_template_has_an_english_translation() -> None:
    values = {
        "brgy": "Batac",
        "tubig": "ULAN",
        "crop": "palay",
        "crop1": "munggo",
        "crop2": "palay",
        "a": "30",
        "b": "12",
        "n": "45",
        "reason1": "sapat ang tubig sa karamihan ng nakaraang tag-araw",
        "reason2": "tumutulong ito sa lupa pagkatapos ng palay",
        "sources": "PinoyRice",
        "priority": "income",
        "rain": "40",
        "soil": "55",
    }
    assert set(ENGLISH) == set(TEMPLATES)
    for template_id in TEMPLATES:
        reply = render(template_id, **values)
        gloss = english_gloss(reply.template_id, reply.text)
        assert gloss, template_id
        assert "{" not in gloss
    for template_id, text in PLAIN_TEMPLATES.items():
        assert english_gloss(template_id, text.format(**values))
    assert english_gloss("T_REFER", WEAK_RETRIEVAL_TEMPLATE)
    why = english_gloss("T_WHY", render("T_WHY", **values).text)
    assert why is not None
    assert "water was enough in most past dry seasons" in why
    assert "it helps the soil after rice" in why
    assert english_gloss("T_HELP", "unrelated text") is None
