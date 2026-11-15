import hashlib
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import BaseRoute

from app.config import Settings
from app.db import connect_db, record_event
from app.main import create_app
from app.templates import render
from web import auth

PASSWORD = "correct horse battery staple"
PHONE_HASH = hashlib.sha256(b"admin-fixture-farmer").hexdigest()
OTHER_HASH = hashlib.sha256(b"admin-fixture-other").hexdigest()
ADMIN_ROUTES = (
    "/admin",
    "/admin/activity",
    "/admin/messages",
    "/admin/farmers",
    "/admin/indicators",
    "/admin/kb",
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=str(tmp_path / "admin.sqlite3"),
        phone_hash_secret=hashlib.sha256(b"admin-fixture-material").hexdigest(),
        admin_password_hash=PasswordHasher().hash(PASSWORD),
        session_secret="x" * 40,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings), base_url="https://testserver") as test_client:
        yield test_client


def sign_in(client: TestClient, password: str = PASSWORD):
    return client.post("/admin/login", data={"password": password}, follow_redirects=False)


@pytest.fixture
def session_client(client: TestClient) -> TestClient:
    assert sign_in(client).status_code == 303
    return client


def csrf_token(client: TestClient) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/admin").text)
    assert match
    return match.group(1)


def seed(settings: Settings) -> None:
    with connect_db(settings.db_path) as connection:
        for digest, brgy in ((PHONE_HASH, "BATAC"), (OTHER_HASH, "BATAC")):
            connection.execute(
                "INSERT INTO farmers (phone_hash, barangay_code, water_source) "
                "VALUES (?, ?, 'ulan')",
                (digest, brgy),
            )
        connection.execute(
            "INSERT INTO messages (phone_hash, direction, text, intent) "
            "VALUES (?, 'in', '<script>alert(1)</script> PLANT', 'PLANT')",
            (PHONE_HASH,),
        )
        connection.execute(
            "INSERT INTO messages (phone_hash, direction, text, intent, template_id) "
            "VALUES (?, 'out', 'Sagot na may haba', 'PLANT', 'T_FALLBACK')",
            (PHONE_HASH,),
        )
        connection.execute(
            "INSERT INTO messages (phone_hash, direction, text, intent) "
            "VALUES (?, 'in', 'HELP', 'HELP')",
            (OTHER_HASH,),
        )
        record_event(connection, "registered", intent="REG", source="keyword")
        record_event(connection, "refusal", intent="PLANT", source="model")


@pytest.mark.parametrize("path", ADMIN_ROUTES)
def test_admin_pages_redirect_without_session(client: TestClient, path: str) -> None:
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"
    assert response.headers["cache-control"] == "no-store"


def test_state_changing_routes_redirect_without_session(client: TestClient) -> None:
    for path in ("/admin/logout", f"/admin/farmers/{PHONE_HASH}/delete"):
        response = client.post(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/login"


def test_login_page_is_public_and_not_indexed(client: TestClient) -> None:
    response = client.get("/admin/login")
    assert response.status_code == 200
    assert 'type="password"' in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"


def test_wrong_password_is_rejected(client: TestClient) -> None:
    response = sign_in(client, "not the password")
    assert response.status_code == 401
    assert auth.COOKIE_NAME not in response.cookies
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_unset_hash_never_signs_in(settings: Settings) -> None:
    unset = Settings(
        db_path=settings.db_path, session_secret=settings.session_secret, admin_password_hash=""
    )
    with TestClient(create_app(unset), base_url="https://testserver") as test_client:
        assert sign_in(test_client, "").status_code == 401


def test_login_sets_signed_cookie_with_required_flags(client: TestClient) -> None:
    response = sign_in(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert f"max-age={8 * 3600}" in cookie
    assert client.get("/admin").status_code == 200


def test_forged_cookie_is_rejected(client: TestClient) -> None:
    client.cookies.set(auth.COOKIE_NAME, "forged.value.here", path="/admin")
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_session_expires_after_eight_hours(
    session_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    future = time.time() + auth.SESSION_SECONDS + 5
    monkeypatch.setattr("itsdangerous.timed.time.time", lambda: future)
    assert session_client.get("/admin", follow_redirects=False).status_code == 303


def test_login_is_rate_limited_per_ip(client: TestClient) -> None:
    for _ in range(auth.LOGIN_LIMIT):
        assert sign_in(client, "wrong").status_code == 401
    blocked = sign_in(client)
    assert blocked.status_code == 429
    assert "15 minutes" in blocked.text
    assert int(blocked.headers["retry-after"]) > 0
    assert auth.COOKIE_NAME not in blocked.cookies


def test_admin_pages_render_with_headers(session_client: TestClient, settings: Settings) -> None:
    seed(settings)
    for path in ADMIN_ROUTES:
        response = session_client.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-robots-tag"] == "noindex"
        assert "Gateway: last event" in response.text
        assert "Session:" in response.text


def test_logout_requires_csrf_and_ends_session(session_client: TestClient) -> None:
    assert session_client.post("/admin/logout", follow_redirects=False).status_code == 403
    assert session_client.get("/admin").status_code == 200
    token = csrf_token(session_client)
    response = session_client.post(
        "/admin/logout", data={"csrf_token": token}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"
    session_client.cookies.clear()
    assert session_client.get("/admin", follow_redirects=False).status_code == 303


def test_delete_without_csrf_is_rejected(session_client: TestClient, settings: Settings) -> None:
    seed(settings)
    url = f"/admin/farmers/{PHONE_HASH}/delete"
    assert session_client.post(url, follow_redirects=False).status_code == 403
    assert session_client.post(url, data={"csrf_token": "wrong"}).status_code == 403
    with connect_db(settings.db_path) as connection:
        assert connection.execute("SELECT count(*) FROM farmers").fetchone()[0] == 2


def test_delete_with_csrf_removes_profile_and_messages(
    session_client: TestClient, settings: Settings
) -> None:
    seed(settings)
    token = csrf_token(session_client)
    response = session_client.post(
        f"/admin/farmers/{PHONE_HASH}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with connect_db(settings.db_path) as connection:
        assert connection.execute("SELECT count(*) FROM farmers").fetchone()[0] == 1
        remaining = connection.execute("SELECT phone_hash FROM messages").fetchall()
    assert [row[0] for row in remaining] == [OTHER_HASH]
    assert "Profile deleted" in session_client.get("/admin/farmers?deleted=1").text


def test_delete_unknown_or_malformed_profile_is_404(session_client: TestClient) -> None:
    token = csrf_token(session_client)
    for target in (OTHER_HASH, "not-a-hash"):
        response = session_client.post(
            f"/admin/farmers/{target}/delete", data={"csrf_token": token}
        )
        assert response.status_code == 404


def test_csrf_token_is_tied_to_session(client: TestClient, settings: Settings) -> None:
    seed(settings)
    sign_in(client)
    token = csrf_token(client)
    with TestClient(create_app(settings), base_url="https://testserver") as other:
        sign_in(other)
        response = other.post(f"/admin/farmers/{PHONE_HASH}/delete", data={"csrf_token": token})
        assert response.status_code == 403


def test_farmers_page_shows_short_hash_and_confirm_dialog(
    session_client: TestClient, settings: Settings
) -> None:
    seed(settings)
    html = session_client.get("/admin/farmers").text
    assert PHONE_HASH[:8] in html
    assert PHONE_HASH not in html.replace(f"/admin/farmers/{PHONE_HASH}/delete", "")
    assert "confirm-dialog" in html
    assert "and its messages will be deleted" in html


def test_messages_escape_text_filter_and_meter(
    session_client: TestClient, settings: Settings
) -> None:
    seed(settings)
    html = session_client.get("/admin/messages").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "/150" in html
    only_out = session_client.get("/admin/messages?direction=out").text
    assert "Sagot na may haba" in only_out
    assert "HELP" not in only_out.split("<tbody>")[1]
    by_intent = session_client.get("/admin/messages?intent=HELP").text
    assert "Sagot na may haba" not in by_intent
    assert "No messages match" in session_client.get("/admin/messages?intent=NOPE").text


def test_activity_filter_by_type(session_client: TestClient, settings: Settings) -> None:
    seed(settings)
    html = session_client.get("/admin/activity?type=refusal").text
    timeline = html.split("<ol", 1)[1]
    assert "Refusal" in timeline
    assert "Registered" not in timeline
    assert "No events of this type" in session_client.get("/admin/activity?type=stop_received").text


def test_empty_states(session_client: TestClient) -> None:
    assert "No profiles yet" in session_client.get("/admin/farmers").text
    assert "No messages match" in session_client.get("/admin/messages").text
    assert "No events yet" in session_client.get("/admin/activity").text
    assert "No activity yet" in session_client.get("/admin").text


def test_dashboard_counts_and_freshness(session_client: TestClient, settings: Settings) -> None:
    seed(settings)
    html = session_client.get("/admin").text
    assert "Latest POWER row" in html
    assert "Latest SMAP day" in html
    assert "Soil wetness source" in html
    assert "50% / 50%" in html


def test_indicators_page_is_locked_and_read_only(session_client: TestClient) -> None:
    html = session_client.get("/admin/indicators").text
    assert "Fixed before the hindcast; changed only in the repo" in html
    assert html.count("<form") == 1  # only the sign-out form
    assert '<td data-label="Barangay">Batac</td>' in html
    assert 'role="img"' in html


def test_kb_page_lists_documents_and_states_restricted_rule(session_client: TestClient) -> None:
    html = session_client.get("/admin/kb").text
    assert "Restricted chunks are not loaded" in html
    assert html.count('class="chip-tag source-chip"') == 19


def test_database_failure_shows_error_state(session_client: TestClient, settings: Settings) -> None:
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("DROP TABLE messages")
    response = session_client.get("/admin/messages")
    assert response.status_code == 503
    assert "could not load its data" in response.text


def app_routes(application: FastAPI) -> Iterator[BaseRoute]:
    """Every route, including those of included routers."""
    for route in application.routes:
        original = getattr(route, "original_router", None)
        yield from original.routes if original is not None else [route]


def test_every_admin_route_is_guarded(client: TestClient) -> None:
    open_routes = {("GET", "/admin/login"), ("POST", "/admin/login")}
    checked: set[tuple[str, str]] = set()
    for route in app_routes(client.app):
        if not isinstance(route, APIRoute) or not route.path.startswith("/admin"):
            continue
        for method in route.methods:
            if (method, route.path) in open_routes:
                continue
            path = route.path.replace("{phone_hash}", PHONE_HASH)
            response = client.request(method, path, follow_redirects=False)
            assert response.status_code == 303, (method, route.path)
            assert response.headers["location"] == "/admin/login", (method, route.path)
            checked.add((method, route.path))
    assert ("POST", "/admin/logout") in checked
    assert ("POST", "/admin/farmers/{phone_hash}/delete") in checked
    assert len(checked) >= 8


def test_non_ascii_csrf_token_is_rejected_not_a_server_error(
    session_client: TestClient, settings: Settings
) -> None:
    seed(settings)
    logout = session_client.post("/admin/logout", data={"csrf_token": "\u00e9"})
    assert logout.status_code == 403
    delete = session_client.post(
        f"/admin/farmers/{PHONE_HASH}/delete", data={"csrf_token": "\u00e9"}
    )
    assert delete.status_code == 403
    assert "text/html" in delete.headers["content-type"]
    assert "Reload the page" in delete.text


def test_unknown_profile_renders_friendly_page(session_client: TestClient) -> None:
    response = session_client.post(
        f"/admin/farmers/{OTHER_HASH}/delete", data={"csrf_token": csrf_token(session_client)}
    )
    assert response.status_code == 404
    assert "Profile not found" in response.text


def test_messages_show_english_translation_for_template_reply(
    session_client: TestClient, settings: Settings
) -> None:
    reply = render("T_FALLBACK")
    with connect_db(settings.db_path) as connection:
        connection.execute(
            "INSERT INTO messages (phone_hash, direction, text, intent, template_id) "
            "VALUES (?, 'out', ?, 'OTHER', ?)",
            (PHONE_HASH, reply.text, reply.template_id),
        )
    html = session_client.get("/admin/messages").text
    assert "English translation" in html
    assert "I did not understand. Text HELP for the list of commands." in html


def test_rejected_post_page_links_back_to_a_get_route(
    session_client: TestClient, settings: Settings
) -> None:
    seed(settings)
    cases = (
        (f"/admin/farmers/{PHONE_HASH}/delete", "Back to Farmers", "/admin/farmers"),
        ("/admin/logout", "Back to Dashboard", "/admin"),
    )
    for url, label, target in cases:
        response = session_client.post(url, data={"csrf_token": "wrong"})
        assert response.status_code == 403
        assert f'href="{target}"' in response.text
        assert label in response.text
        assert "Reload</a>" not in response.text
        assert session_client.get(target).status_code == 200
