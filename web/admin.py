"""Admin panel: sign-in, dashboard, activity, messages, farmers, indicators, knowledge base."""

import csv
import logging
import re
import sqlite3
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from app.db import DATA, connect_db
from app.templates import SMS_LIMIT, sms_length
from engine import params
from web import auth
from web.auth import Session, require_session
from web.public import STATIC, client_address, templates
from web.translate import english_gloss

logger = logging.getLogger(__name__)

LOGO_ICON = STATIC / "img" / "logo-icon.png"
templates.env.globals["logo_icon_available"] = LOGO_ICON.exists

GATEWAY_STALE_HOURS = 24
POWER_STALE_DAYS = 3
SMAP_STALE_DAYS = 7
MESSAGE_LIMIT = 200
ACTIVITY_LIMIT = 200
FEED_LIMIT = 8
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
POWER_FILES = (
    DATA / "power" / "power_daily_2026.csv",
    DATA / "power" / "power_daily_1981_2025.csv",
)

NAV = (
    ("dashboard", "/admin", "Dashboard"),
    ("activity", "/admin/activity", "Activity"),
    ("messages", "/admin/messages", "Messages"),
    ("farmers", "/admin/farmers", "Farmers"),
    ("indicators", "/admin/indicators", "Indicators"),
    ("kb", "/admin/kb", "Knowledge base"),
)

EVENT_LABELS = {
    "registered": "Registered",
    "recommendation_sent": "Recommendation sent",
    "command_handled": "Command handled",
    "fallback_used": "Fallback used",
    "refusal": "Refusal",
    "model_call_failed": "Model call failed",
    "duplicate_dropped": "Duplicate dropped",
    "rate_limit_hit": "Rate limit hit",
    "stop_received": "STOP received",
    "send_failed": "Send failed",
    "non_mobile_ignored": "Non-mobile ignored",
}
ATTENTION_EVENTS = frozenset({"refusal", "model_call_failed", "rate_limit_hit", "send_failed"})

ENSO_RULE = (
    "An El Nino episode is 5 or more consecutive overlapping seasons with ONI at or above +0.5. "
    "A dry season runs November Y to April Y+1 and takes the phase of the DJF season centered "
    "on January Y+1."
)

router = APIRouter(prefix="/admin")
guarded = APIRouter(prefix="/admin", dependencies=[Depends(require_session)])


def add_admin_headers(response: Response, path: str) -> None:
    """Keep admin pages out of caches and search engines."""
    if path == "/admin" or path.startswith("/admin/"):
        for name, value in auth.NO_STORE.items():
            response.headers[name] = value


def parse_time(value: str | None) -> datetime | None:
    """Parse a SQLite CURRENT_TIMESTAMP value (UTC)."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def ago(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "never"
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def short_hash(value: str) -> str:
    return value[:8]


def event_label(event_type: str) -> str:
    return EVENT_LABELS.get(event_type, event_type.replace("_", " ").capitalize())


templates.env.filters["short_hash"] = short_hash
templates.env.filters["event_label"] = event_label


def gateway_chip(connection: sqlite3.Connection, now: datetime) -> dict[str, str]:
    row = connection.execute("SELECT max(created_at) FROM events").fetchone()
    last = parse_time(row[0])
    if last is None:
        return {"state": "idle", "label": "Gateway: no events yet"}
    stale = (now - last).total_seconds() > GATEWAY_STALE_HOURS * 3600
    return {
        "state": "stale" if stale else "ok",
        "label": f"Gateway: last event {ago(last, now)}",
    }


def render_page(
    request: Request,
    session: Session,
    template: str,
    active: str,
    build: Callable[[sqlite3.Connection, datetime], dict[str, Any]],
    status_code: int = 200,
) -> Response:
    """Render an admin page; a database failure shows the error state instead of a trace."""
    now = datetime.now(UTC)
    context: dict[str, Any]
    try:
        with connect_db(request.app.state.settings.db_path) as connection:
            chip = gateway_chip(connection, now)
            context = build(connection, now)
    except (sqlite3.Error, OSError):
        logger.exception("Admin page %s failed to load its data", active)
        template, status_code = "admin/error.html", 503
        chip = {"state": "idle", "label": "Gateway: unknown"}
        context = {}
    return templates.TemplateResponse(
        request,
        template,
        {
            "page": "admin",
            "active": active,
            "nav": NAV,
            "chip": chip,
            "csrf_token": session.csrf_token,
            "minutes_left": session.seconds_left // 60,
            **context,
        },
        status_code=status_code,
    )


# --- sign-in -------------------------------------------------------------------------------


CSRF_MESSAGE = "The form expired or was not sent from this panel. Reload the page and try again."
BACK_DASHBOARD = ("/admin", "Back to Dashboard")
BACK_FARMERS = ("/admin/farmers", "Back to Farmers")
PROFILE_MESSAGE = "That profile does not exist. It may already have been deleted."


def problem(
    request: Request,
    session: Session,
    status_code: int,
    title: str,
    message: str,
    back: tuple[str, str],
) -> Response:
    """Friendly error page for a rejected request."""
    return render_page(
        request,
        session,
        "admin/error.html",
        "",
        lambda connection, now: {"title": title, "message": message, "back": back},
        status_code,
    )


def login_response(
    request: Request, status_code: int = 200, error: str = "", notice: str = ""
) -> Response:
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {"page": "admin", "error": error, "notice": notice},
        status_code=status_code,
    )


@router.get("/login")
def login_form(request: Request) -> Response:
    settings = request.app.state.settings
    if auth.read_session(request.cookies.get(auth.COOKIE_NAME), settings.session_secret):
        return RedirectResponse("/admin", status_code=303)
    return login_response(request)


@router.post("/login")
async def login(request: Request, password: Annotated[str, Form()] = "") -> Response:
    settings = request.app.state.settings
    limiter = request.app.state.login_limiter
    address = client_address(request)
    if not limiter.allow(address):
        response = login_response(
            request,
            429,
            error="Too many attempts. Try again in 15 minutes.",
        )
        response.headers["Retry-After"] = str(limiter.retry_after(address))
        return response
    if not settings.session_secret:
        return login_response(request, 503, error="Sign-in is not configured.")
    valid = await run_in_threadpool(auth.verify_password, password, settings.admin_password_hash)
    if not valid:
        return login_response(request, 401, error="That password is not correct.")
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.new_session_cookie(settings.session_secret),
        max_age=auth.SESSION_SECONDS,
        path="/admin",
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@guarded.post("/logout")
def logout(
    request: Request,
    session: Annotated[Session, Depends(require_session)],
    csrf_token: Annotated[str, Form()] = "",
) -> Response:
    if not auth.csrf_valid(session, csrf_token):
        return problem(request, session, 403, "Request not accepted", CSRF_MESSAGE, BACK_DASHBOARD)
    response = RedirectResponse(auth.LOGIN_URL, status_code=303)
    response.delete_cookie(auth.COOKIE_NAME, path="/admin", secure=True, httponly=True)
    return response


# --- data helpers --------------------------------------------------------------------------


def latest_power_date() -> date | None:
    """Date of the newest POWER row that carries a measurement."""
    for path in POWER_FILES:
        if not path.exists():
            continue
        with path.open(newline="") as handle:
            dates = [r["date"] for r in csv.DictReader(handle) if r["prectotcorr_mm"]]
        if dates:
            return date.fromisoformat(max(dates))
    return None


def freshness(moment: date | None, today: date, limit_days: int) -> dict[str, Any]:
    if moment is None:
        return {"date": "no data", "stale": True, "age": ""}
    days = (today - moment).days
    return {"date": moment.isoformat(), "stale": days > limit_days, "age": f"{days} d old"}


def share(count: int, total: int) -> int:
    return round(100 * count / total) if total else 0


def build_dashboard(connection: sqlite3.Connection, now: datetime) -> dict[str, Any]:
    profiles = connection.execute("SELECT count(*) FROM farmers").fetchone()[0]
    messages = connection.execute(
        "SELECT count(*) FROM messages WHERE created_at >= datetime('now', '-1 day')"
    ).fetchone()[0]
    sources = Counter(
        {
            row["source"]: row["n"]
            for row in connection.execute(
                """SELECT source, count(*) AS n FROM events
                WHERE source IS NOT NULL AND created_at >= datetime('now', '-1 day')
                GROUP BY source"""
            )
        }
    )
    total = sum(sources.values())
    soilwet = connection.execute(
        """SELECT soilwet_source FROM indicators WHERE soilwet_source IS NOT NULL
        ORDER BY updated_at DESC, soilwet_date DESC LIMIT 1"""
    ).fetchone()
    smap_row = connection.execute(
        "SELECT max(soilwet_date) FROM indicators WHERE soilwet_source = 'smap'"
    ).fetchone()
    smap_day = date.fromisoformat(smap_row[0]) if smap_row[0] else None
    today = now.date()
    return {
        "profiles": profiles,
        "messages_24h": messages,
        "total_answered": total,
        "model_share": share(sources["model"], total),
        "template_share": share(total - sources["model"], total),
        "power": freshness(latest_power_date(), today, POWER_STALE_DAYS),
        "smap": freshness(smap_day, today, SMAP_STALE_DAYS),
        "soilwet_source": soilwet[0] if soilwet else None,
        "feed": events(connection, "", FEED_LIMIT, now),
    }


def events(
    connection: sqlite3.Connection, event_type: str, limit: int, now: datetime
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT id, type, intent, template_id, source, latency_ms, created_at FROM events
        WHERE (? = '' OR type = ?) ORDER BY id DESC LIMIT ?""",
        (event_type, event_type, limit),
    ).fetchall()
    return [
        {
            **dict(row),
            "ago": ago(parse_time(row["created_at"]), now),
            "attention": row["type"] in ATTENTION_EVENTS,
        }
        for row in rows
    ]


# --- pages ---------------------------------------------------------------------------------


@guarded.get("")
def dashboard(request: Request, session: Annotated[Session, Depends(require_session)]) -> Response:
    return render_page(request, session, "admin/dashboard.html", "dashboard", build_dashboard)


@guarded.get("/activity")
def activity(
    request: Request, session: Annotated[Session, Depends(require_session)], type: str = ""
) -> Response:
    def build(connection: sqlite3.Connection, now: datetime) -> dict[str, Any]:
        present = [
            row[0] for row in connection.execute("SELECT DISTINCT type FROM events ORDER BY type")
        ]
        return {
            "events": events(connection, type, ACTIVITY_LIMIT, now),
            "event_types": sorted(set(present) | set(EVENT_LABELS), key=event_label),
            "selected": type,
            "limit": ACTIVITY_LIMIT,
        }

    return render_page(request, session, "admin/activity.html", "activity", build)


@guarded.get("/messages")
def messages(
    request: Request,
    session: Annotated[Session, Depends(require_session)],
    intent: str = "",
    template: str = "",
    direction: str = "",
) -> Response:
    def build(connection: sqlite3.Connection, now: datetime) -> dict[str, Any]:
        rows = connection.execute(
            """SELECT id, phone_hash, direction, text, intent, template_id, created_at
            FROM messages
            WHERE (? = '' OR intent = ?) AND (? = '' OR template_id = ?)
              AND (? = '' OR direction = ?)
            ORDER BY id DESC LIMIT ?""",
            (intent, intent, template, template, direction, direction, MESSAGE_LIMIT),
        ).fetchall()
        entries = []
        for row in rows:
            outbound = row["direction"] == "out"
            length = sms_length(row["text"])
            entries.append(
                {
                    **dict(row),
                    "outbound": outbound,
                    "length": length,
                    "over_limit": length > SMS_LIMIT,
                    "length_percent": min(100, round(100 * length / SMS_LIMIT)),
                    "gloss": english_gloss(row["template_id"], row["text"])
                    if outbound and row["template_id"]
                    else None,
                }
            )
        intents = connection.execute(
            "SELECT DISTINCT intent FROM messages WHERE intent IS NOT NULL ORDER BY 1"
        ).fetchall()
        template_ids = connection.execute(
            "SELECT DISTINCT template_id FROM messages WHERE template_id IS NOT NULL ORDER BY 1"
        ).fetchall()
        return {
            "messages": entries,
            "intents": [row[0] for row in intents],
            "template_ids": [row[0] for row in template_ids],
            "selected": {"intent": intent, "template": template, "direction": direction},
            "sms_limit": SMS_LIMIT,
            "limit": MESSAGE_LIMIT,
        }

    return render_page(request, session, "admin/messages.html", "messages", build)


@guarded.get("/farmers")
def farmers(
    request: Request,
    session: Annotated[Session, Depends(require_session)],
    deleted: str = "",
) -> Response:
    def build(connection: sqlite3.Connection, now: datetime) -> dict[str, Any]:
        rows = connection.execute(
            """SELECT f.phone_hash, f.barangay_code, b.name AS barangay, f.water_source,
                      f.last_crop, f.priority, f.created_at
            FROM farmers f LEFT JOIN barangays b ON b.barangay_code = f.barangay_code
            ORDER BY f.created_at DESC, f.phone_hash"""
        ).fetchall()
        return {"farmers": [dict(row) for row in rows], "deleted": deleted == "1"}

    return render_page(request, session, "admin/farmers.html", "farmers", build)


@guarded.post("/farmers/{phone_hash}/delete")
def delete_farmer(
    request: Request,
    phone_hash: str,
    session: Annotated[Session, Depends(require_session)],
    csrf_token: Annotated[str, Form()] = "",
) -> Response:
    if not auth.csrf_valid(session, csrf_token):
        return problem(request, session, 403, "Request not accepted", CSRF_MESSAGE, BACK_FARMERS)
    if not HASH_PATTERN.fullmatch(phone_hash):
        return problem(request, session, 404, "Profile not found", PROFILE_MESSAGE, BACK_FARMERS)
    with connect_db(request.app.state.settings.db_path) as connection:
        deleted = connection.execute("DELETE FROM farmers WHERE phone_hash = ?", (phone_hash,))
        connection.execute("DELETE FROM messages WHERE phone_hash = ?", (phone_hash,))
        connection.execute(
            "UPDATE processed_events SET phone_hash = NULL WHERE phone_hash = ?", (phone_hash,)
        )
    if deleted.rowcount == 0:
        return problem(request, session, 404, "Profile not found", PROFILE_MESSAGE, BACK_FARMERS)
    return RedirectResponse("/admin/farmers?deleted=1", status_code=303)


@guarded.get("/indicators")
def indicators(request: Request, session: Annotated[Session, Depends(require_session)]) -> Response:
    def build(connection: sqlite3.Connection, now: datetime) -> dict[str, Any]:
        rows = connection.execute(
            """SELECT i.*, b.name AS barangay FROM indicators i
            LEFT JOIN barangays b ON b.barangay_code = i.barangay_code
            ORDER BY i.crop, i.sow_window, i.barangay_code"""
        ).fetchall()
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            entry = dict(row)
            entry["percent"] = share(row["n_adequate"], row["n_years"])
            entry["percent_elnino"] = share(row["n_adequate_elnino"], row["n_elnino"])
            groups.setdefault((row["crop"], row["sow_window"]), []).append(entry)
        return {
            "groups": [
                {"crop": crop, "window": window, "rows": group}
                for (crop, window), group in groups.items()
            ],
            "thresholds": [
                ("Adequate season: water ratio at least", params.ADEQUACY_THRESHOLD),
                ("Water counts as OK: reliability at least", params.WATER_OK_RELIABILITY),
                ("Timing risk reported above", params.TIMING_REASON_FREQUENCY),
                ("Heat threshold (degrees C)", params.HEAT_THRESHOLD_C),
                ("Harvest rain threshold (mm)", params.HARVEST_RAIN_THRESHOLD_MM),
            ],
            "weights": list(params.SCORING_WEIGHTS.items()),
            "enso_rule": ENSO_RULE,
        }

    return render_page(request, session, "admin/indicators.html", "indicators", build)


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA / "kb" / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


@guarded.get("/kb")
def knowledge_base(
    request: Request, session: Annotated[Session, Depends(require_session)]
) -> Response:
    def build(connection: sqlite3.Connection, now: datetime) -> dict[str, Any]:
        sources = read_csv("kb_sources.csv")
        chunks = [row for row in read_csv("kb_chunks.csv") if row["restricted"] == "0"]
        per_doc = Counter(row["doc_id"] for row in chunks)
        by_topic = Counter((row["crop"] or "general", row["topic"] or "general") for row in chunks)
        return {
            "documents": [{**row, "usable_chunks": per_doc[row["doc_id"]]} for row in sources],
            "topics": sorted(
                (
                    {"crop": crop, "topic": topic, "count": n}
                    for (crop, topic), n in by_topic.items()
                ),
                key=lambda item: (item["crop"], item["topic"]),
            ),
            "usable_total": len(chunks),
        }

    return render_page(request, session, "admin/kb.html", "kb", build)
