"""Public pages, simulator endpoint and indicator JSON."""

import csv
import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.db import DATA, connect_db
from web.translate import english_gloss

WEB = Path(__file__).resolve().parent
STATIC = WEB / "static"
LOGO = STATIC / "img" / "logo.png"
REPO_URL = "https://github.com/17eb/agrichat"
CHART_JS_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"
CHART_JS_SRI = "sha384-vsrfeLOOY6KuIYKDlmVH5UiBmgIdB1oEf7p01YgWHuqmOHfZr374+odEv96n9tNC"
SIMULATE_LIMIT = 20
SIMULATE_WINDOW_SECONDS = 600
SENDER_PATTERN = r"^sim-[0-9a-f]{32}$"
SMAP_VS_POWER = DATA / "smap" / "smap_vs_power.csv"

router = APIRouter()
templates = Jinja2Templates(directory=WEB / "templates")
templates.env.globals["logo_available"] = LOGO.exists
templates.env.globals["repo_url"] = REPO_URL
templates.env.globals["chart_js_url"] = CHART_JS_URL
templates.env.globals["chart_js_sri"] = CHART_JS_SRI


class SimulatorGateway:
    """Gateway that sends nothing; simulator replies go back in the HTTP response."""

    def send(self, recipient: str, text: str) -> None:
        return None


class SimulateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sender: Annotated[str, StringConstraints(pattern=SENDER_PATTERN)] = Field(alias="from")
    text: str = Field(min_length=1, max_length=500)


def client_address(request: Request) -> str:
    """The caller's address; behind the local reverse proxy, the proxy's forwarded value."""
    host = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for", "")
    if host in {"127.0.0.1", "::1"} and forwarded:
        return forwarded.split(",")[-1].strip()
    return host


def smap_comparison() -> tuple[list[str], list[list[str]]]:
    """Header and rows of the SMAP-versus-POWER comparison, empty until that file exists."""
    if not SMAP_VS_POWER.exists():
        return [], []
    with SMAP_VS_POWER.open(newline="") as handle:
        rows = list(csv.reader(handle))
    return (rows[0], rows[1:]) if rows else ([], [])


@router.get("/")
def home(request: Request) -> Any:
    return templates.TemplateResponse(request, "home.html", {"page": "home"})


@router.get("/data")
def data_page(request: Request) -> Any:
    header, rows = smap_comparison()
    return templates.TemplateResponse(
        request, "data.html", {"page": "data", "smap_header": header, "smap_rows": rows}
    )


@router.post("/simulate")
async def simulate(request: Request, body: SimulateRequest) -> JSONResponse:
    limiter = request.app.state.simulate_limiter
    address = client_address(request)
    if not limiter.allow(address):
        return JSONResponse(
            {"detail": "Too many messages. Please wait a few minutes."},
            status_code=429,
            headers={"Retry-After": str(limiter.retry_after(address))},
        )
    if not request.app.state.settings.phone_hash_secret:
        raise HTTPException(status_code=503, detail="The simulator is not configured")
    reply = await run_in_threadpool(
        request.app.state.simulator_handler.handle, body.sender, body.text
    )
    return JSONResponse(
        {
            "reply": reply.text,
            "length": len(reply.text),
            "template_id": reply.template_id,
            "translation": english_gloss(reply.template_id, reply.text),
        }
    )


@router.get("/indicators/{barangay_code}")
def indicators(request: Request, barangay_code: str) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", barangay_code):
        raise HTTPException(status_code=404, detail="Unknown barangay")
    with connect_db(request.app.state.settings.db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM indicators WHERE barangay_code = ? ORDER BY crop, sow_window",
            (barangay_code.upper(),),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No indicators for this barangay")
    return [dict(row) for row in rows]
