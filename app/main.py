"""Server-rendered UI for the local, fake-data Member Service Portal."""

import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.data import MEMBERS

APP_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Member Service Portal", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def search(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={"member_id": "", "error": None},
    )


@app.get("/member", response_class=HTMLResponse)
def member_details(request: Request, member_id: str = ""):
    member_id = member_id.strip()
    error = None
    if not member_id:
        error = "Please enter a Member ID."
    elif re.fullmatch(r"[0-9]{5}", member_id) is None:
        error = "Member ID must contain exactly 5 digits."

    if error:
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context={"member_id": member_id, "error": error},
        )

    member = MEMBERS.get(member_id)
    balance = None
    if member:
        dollars, cents = divmod(member["balance_cents"], 100)
        balance = f"${dollars:,}.{cents:02d}"
    return templates.TemplateResponse(
        request=request,
        name="member.html",
        context={"member_id": member_id, "member": member, "balance": balance},
    )
