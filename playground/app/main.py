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


@app.post("/api/run")
async def run_code(body: RunRequest):
    if not body.session_id.strip():
        raise HTTPException(400, "session_id must not be empty")
    if not body.code.strip():
        raise HTTPException(400, "code must not be empty")
    token = _mint_jwt(body.session_id)
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.post(
                f"{SANDBOX_URL}/run",
                json={"code": body.code},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.ConnectError:
            raise HTTPException(502, "sandbox unreachable")
    if resp.status_code == 401:
        raise HTTPException(502, "sandbox auth error")
    if resp.status_code == 400:
        raise HTTPException(400, resp.json().get("detail", "bad request"))
    return resp.json()


@app.get("/api/status/{session_id}")
async def get_status(session_id: str):
    token = _mint_jwt(session_id)
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                f"{SANDBOX_URL}/status",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.ConnectError:
            return {"files": [], "workspace_exists": False}
    return resp.json()


# Static files — must be last so API routes take priority
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
