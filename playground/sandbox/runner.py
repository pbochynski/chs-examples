import os
import re
import site
import subprocess
import sys
import time
from pathlib import Path
from subprocess import TimeoutExpired

import jwt
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()

JWT_SECRET = os.environ["JWT_SECRET"]
WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))


def _verify(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing token")
    token = authorization.removeprefix("Bearer ")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "invalid token")
    sub = payload.get("sub", "")
    if not sub:
        raise HTTPException(401, "missing sub")
    return sub


def _sanitize_session(session_id: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_\-.]", "_", session_id)
    if not clean or clean.startswith("."):
        raise HTTPException(400, "invalid session id")
    return clean


def _workspace(session_id: str) -> Path:
    safe = _sanitize_session(session_id)
    p = WORKSPACE_ROOT / safe
    p.mkdir(parents=True, exist_ok=True)
    return p


def _list_files(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return sorted(
        [{"name": f.name, "size": f.stat().st_size} for f in path.iterdir() if f.is_file()],
        key=lambda x: x["name"],
    )


class RunRequest(BaseModel):
    code: str


@app.post("/run")
def run_code(body: RunRequest, authorization: str | None = Header(default=None)):
    session_id = _verify(authorization)
    code = body.code.strip()
    if not code:
        raise HTTPException(400, "code must not be empty")
    workspace = _workspace(session_id)
    # Include the user site-packages dir in PYTHONPATH so packages installed
    # via `pip install --user` (the default for non-root) are importable in
    # the same code block that ran the pip install.
    user_site = site.getusersitepackages()
    env = os.environ.copy()
    env["PYTHONPATH"] = user_site + os.pathsep + env.get("PYTHONPATH", "")
    start = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            timeout=10, cwd=workspace, env=env,
        )
    except TimeoutExpired:
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            "stdout": "",
            "stderr": "(timed out after 10s)",
            "duration_ms": duration_ms,
            "files": _list_files(workspace),
        }
    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_ms": duration_ms,
        "files": _list_files(workspace),
    }


@app.get("/status")
def status(authorization: str | None = Header(default=None)):
    session_id = _verify(authorization)
    safe = _sanitize_session(session_id)
    workspace = WORKSPACE_ROOT / safe
    return {
        "files": _list_files(workspace),
        "workspace_exists": workspace.exists(),
    }
