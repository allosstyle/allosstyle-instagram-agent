"""ALLOS STYLE Instagram agent - starter service (step 1).

What this version does:
  GET /health    public health check (used by Render)
  GET /          password-protected status page
  GET /diagnose  password-protected: tests your Instagram token against both
                 Meta API hosts and tells you which one accepts it

Settings are read from environment variables (set them in Render, never in code):
  ADMIN_PASSWORD   password for this app (username can be anything)
  IG_TOKEN         your Instagram access token
  IG_USER_ID       your Instagram account ID (the long number in the Meta dashboard)
  GRAPH_VERSION    optional, defaults to v26.0
"""
import os
import secrets
from html import escape

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI(title="ALLOS STYLE Instagram agent")
security = HTTPBasic()

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
IG_TOKEN = os.environ.get("IG_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v26.0")


def require_login(creds: HTTPBasicCredentials = Depends(security)) -> None:
    """Block everything unless the right password is given.
    If ADMIN_PASSWORD is not set, nobody can log in (safe default)."""
    ok = bool(ADMIN_PASSWORD) and secrets.compare_digest(
        creds.password.encode(), ADMIN_PASSWORD.encode()
    )
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Wrong or missing password",
            headers={"WWW-Authenticate": "Basic"},
        )


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def home() -> str:
    def status(value: str) -> str:
        return "set" if value else "MISSING"

    rows = "".join(
        f"<tr><td>{escape(name)}</td><td>{status(val)}</td></tr>"
        for name, val in [
            ("ADMIN_PASSWORD", ADMIN_PASSWORD),
            ("IG_TOKEN", IG_TOKEN),
            ("IG_USER_ID", IG_USER_ID),
        ]
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ALLOS STYLE agent</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:560px;margin:2rem auto;padding:0 1rem}}
td{{padding:.3rem 1rem .3rem 0}}
</style></head><body>
<h1>ALLOS STYLE agent</h1>
<p>The service is running. Settings:</p>
<table>{rows}</table>
<p><a href="/diagnose">Test the Instagram connection</a></p>
</body></html>"""


async def probe(client: httpx.AsyncClient, host: str, path: str, fields: str) -> dict:
    """Ask one Meta API host about the account. The token is never returned."""
    url = f"https://{host}/{GRAPH_VERSION}/{path}"
    try:
        resp = await client.get(
            url, params={"fields": fields, "access_token": IG_TOKEN}
        )
        body = resp.json()
    except Exception as exc:  # network problem or non-JSON reply
        return {"ok": False, "problem": type(exc).__name__}

    if resp.status_code == 200 and isinstance(body, dict) and "error" not in body:
        return {"ok": True, "data": body}

    err = body.get("error", {}) if isinstance(body, dict) else {}
    return {
        "ok": False,
        "http_status": resp.status_code,
        "code": err.get("code"),
        "message": err.get("message"),
    }


@app.get("/diagnose", dependencies=[Depends(require_login)])
async def diagnose() -> JSONResponse:
    if not IG_TOKEN or not IG_USER_ID:
        return JSONResponse(
            {"ok": False, "problem": "IG_TOKEN and/or IG_USER_ID are not set in Render."},
            status_code=400,
        )

    async with httpx.AsyncClient(timeout=20) as client:
        facebook_host = await probe(
            client, "graph.facebook.com", IG_USER_ID, "id,username,media_count"
        )
        instagram_host = await probe(
            client, "graph.instagram.com", "me", "user_id,username,media_count"
        )

    if facebook_host["ok"]:
        verdict = "Token works on graph.facebook.com. Use that host."
    elif instagram_host["ok"]:
        verdict = "Token works on graph.instagram.com. Use that host."
    else:
        verdict = "Neither host accepted the token. Check the token and account ID."

    return JSONResponse(
        {
            "verdict": verdict,
            "graph.facebook.com": facebook_host,
            "graph.instagram.com": instagram_host,
        }
    )
