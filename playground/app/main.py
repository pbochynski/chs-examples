import os
import time
from pathlib import Path

import httpx
import jwt
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from snippets import SNIPPETS

app = FastAPI()

JWT_SECRET = os.environ["JWT_SECRET"]
SANDBOX_HOST = os.environ.get("SANDBOX_HOST", "localhost:8080")
SANDBOX_URL = f"http://{SANDBOX_HOST}"

STATIC_DIR = Path(__file__).parent / "static"


def _mint_jwt(session_id: str) -> str:
    return jwt.encode(
        {"sub": session_id, "exp": int(time.time()) + 60},
        JWT_SECRET,
        algorithm="HS256",
    )


class RunRequest(BaseModel):
    session_id: str
    code: str


@app.get("/api/snippets")
def list_snippets():
    return SNIPPETS


def _sandbox_error(resp: httpx.Response) -> str:
    """Extract a plain-text error message from a non-2xx sandbox response."""
    try:
        return resp.json().get("detail", resp.text) if resp.text else f"HTTP {resp.status_code}"
    except Exception:
        return resp.text or f"HTTP {resp.status_code}"


@app.post("/api/run")
async def run_code(body: RunRequest):
    if not body.session_id.strip():
        raise HTTPException(400, "session_id must not be empty")
    if not body.code.strip():
        raise HTTPException(400, "code must not be empty")
    token = _mint_jwt(body.session_id)
    async with httpx.AsyncClient(timeout=65) as client:
        try:
            resp = await client.post(
                f"{SANDBOX_URL}/run",
                json={"code": body.code},
                headers={"Authorization": f"Bearer {token}"},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise HTTPException(502, "sandbox unreachable")
    if resp.status_code == 401:
        # 401 from sandbox = JWT_SECRET mismatch between app and sandbox env vars
        raise HTTPException(502, "sandbox auth error — check JWT_SECRET matches in both assets")
    if not resp.is_success:
        raise HTTPException(resp.status_code, _sandbox_error(resp))
    return resp.json()


@app.get("/api/status/{session_id}")
async def get_status(session_id: str):
    token = _mint_jwt(session_id)
    async with httpx.AsyncClient(timeout=65) as client:
        try:
            resp = await client.get(
                f"{SANDBOX_URL}/status",
                headers={"Authorization": f"Bearer {token}"},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return {"files": [], "workspace_exists": False}
    if not resp.is_success:
        raise HTTPException(resp.status_code, _sandbox_error(resp))
    return resp.json()


# Static files — must be last so API routes take priority
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
