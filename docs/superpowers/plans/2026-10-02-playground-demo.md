# Playground Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained Python code playground demo that shows container-hosting's power — two assets, one YAML, production-grade per-user sandbox isolation — deployable in under 5 minutes.

**Architecture:** A FastAPI service serves a vanilla-JS SPA and proxies code execution requests to a per-user sandbox agent. The sandbox runner executes Python code in isolated `/workspace/<session>/` directories. Container-hosting routes each JWT `sub` to its own sandbox container automatically.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, PyJWT, httpx (service); Python 3.12-slim, FastAPI, uvicorn, PyJWT (sandbox); vanilla HTML/JS + Prism.js (SPA); container-hosting REST API (deploy script)

**Spec:** `docs/superpowers/specs/2026-10-02-playground-demo-design.md`

## Global Constraints

- Python 3.12 only — no 3.11 or 3.13
- No Node.js build toolchain — SPA is plain HTML + JS, Prism.js vendored or CDN
- No external runtime dependencies beyond PyPI packages listed per task
- JWT signed HS256, secret from `JWT_SECRET` env var, 60-second expiry
- Sandbox executes code via `subprocess.run` with 10-second timeout
- Workspace path: `/workspace/<session_id>/` — created on first run
- `SANDBOX_HOST` env var in service (not `REQUIRES_SANDBOX_HOST`) — see spec Known Platform Quirk
- All files live under `playground/` in the `examples` repo
- `idleTTL: 1m` in solution.yaml for demo-friendly expiry

## Review Focus

1. **Session ID containing path traversal chars** (e.g. `../etc`) passed to sandbox — workspace path must be sanitized before use as a directory name; test that `../evil` is rejected with 400.
2. **Code execution timeout** — a snippet with `import time; time.sleep(30)` must return after 10s, not hang the sandbox server; test the timeout path explicitly.
3. **JWT minted by service but validated by sandbox** — a request to the sandbox with no Authorization header, an expired token, or a token signed with the wrong secret must return 401, not execute code.
4. **Empty or whitespace-only code** — `POST /api/run` with `code: "   "` should return a useful error, not spawn a subprocess with empty content.
5. **pip install snippet egress** — `pip install cowsay` requires `pypi.org` and `files.pythonhosted.org` in the egress allowlist; validate these are present in `solution.yaml`.

---

## File Map

```
playground/
├── app/
│   ├── main.py            # FastAPI service: /api/snippets, /api/run, /api/status/{id}, serves static
│   ├── snippets.py        # six curated snippet definitions (id, title, description, code)
│   ├── static/
│   │   ├── index.html     # SPA shell: three-column layout, session switcher, snippet tabs
│   │   └── app.js         # SPA logic: localStorage sessions, fetch /api/run, render output
│   └── Dockerfile         # FROM python:3.12-slim, installs deps, copies app/
├── sandbox/
│   ├── runner.py          # FastAPI sandbox: POST /run, GET /status — JWT auth, subprocess exec
│   └── Dockerfile         # FROM python:3.12-slim, installs deps, copies sandbox/
├── build-config.json      # inline Dockerfiles for service + agent asset types
├── solution.yaml          # SolutionDeployment: app (service) + sandbox (agent)
├── deploy.sh              # zip → POST /sources → poll → PUT /solutions
└── README.md              # 3-step getting started
```

---

## Task 1: Sandbox runner (`sandbox/runner.py`)

**Files:**
- Create: `playground/sandbox/runner.py`
- Create: `playground/sandbox/Dockerfile`
- Test: manual `curl` commands (no pytest — tested via integration in Task 5)

**Interfaces:**
- Produces:
  - `POST /run` — body: `{"code": str}`, header: `Authorization: Bearer <jwt>` → `{"stdout": str, "stderr": str, "duration_ms": int, "files": [{"name": str, "size": int}]}`
  - `GET /status` — header: `Authorization: Bearer <jwt>` → `{"files": [{"name": str, "size": int}], "workspace_exists": bool}`
  - Both endpoints extract `sub` from JWT; 401 on missing/invalid/expired token

- [ ] **Step 1: Create `playground/sandbox/runner.py`**

```python
import os
import subprocess
import time
from pathlib import Path

import jwt
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()

JWT_SECRET = os.environ["JWT_SECRET"]
WORKSPACE_ROOT = Path("/workspace")


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
    # Prevent path traversal: keep only alphanumeric, dash, underscore, dot
    import re
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
    start = time.monotonic()
    result = subprocess.run(
        ["python", "-c", code],
        capture_output=True, text=True,
        timeout=10, cwd=workspace,
    )
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
```

- [ ] **Step 2: Create `playground/sandbox/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY runner.py .
RUN pip install fastapi uvicorn pyjwt --no-cache-dir
CMD ["uvicorn", "runner:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 3: Smoke-test locally**

```bash
cd playground/sandbox
JWT_SECRET=testsecret uvicorn runner:app --port 8080 &

# generate a test token (Python one-liner)
TOKEN=$(python3 -c "import jwt,time; print(jwt.encode({'sub':'alice','exp':int(time.time())+60},'testsecret','HS256'))")

# test /run
curl -s -X POST http://localhost:8080/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"code":"print(\"hello from alice\")"}' | python3 -m json.tool

# test path traversal rejection
TOKEN2=$(python3 -c "import jwt,time; print(jwt.encode({'sub':'../evil','exp':int(time.time())+60},'testsecret','HS256'))")
curl -s -X POST http://localhost:8080/run \
  -H "Authorization: Bearer $TOKEN2" \
  -H "Content-Type: application/json" \
  -d '{"code":"print(1)"}' | python3 -m json.tool
# Expected: {"detail":"invalid session id"} with 400

# test missing auth
curl -s -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{"code":"print(1)"}' | python3 -m json.tool
# Expected: 401

# test timeout (needs 10s to confirm — use sleep 11)
curl -s -X POST http://localhost:8080/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"code":"import time; time.sleep(11)"}' | python3 -m json.tool
# Expected: stderr contains "timed out" or subprocess.TimeoutExpired traceback

kill %1
```

Note: `subprocess.TimeoutExpired` will bubble as a 500 unless caught. Add a handler:

```python
from subprocess import TimeoutExpired

@app.post("/run")
def run_code(body: RunRequest, authorization: str | None = Header(default=None)):
    session_id = _verify(authorization)
    code = body.code.strip()
    if not code:
        raise HTTPException(400, "code must not be empty")
    workspace = _workspace(session_id)
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["python", "-c", code],
            capture_output=True, text=True,
            timeout=10, cwd=workspace,
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
```

Update `runner.py` with this version.

- [ ] **Step 4: Commit**

```bash
git add playground/sandbox/
git commit -m "feat(sandbox): add Python sandbox runner with JWT auth"
```

---

## Task 2: Snippets and service backend (`app/main.py`, `app/snippets.py`)

**Files:**
- Create: `playground/app/snippets.py`
- Create: `playground/app/main.py`

**Interfaces:**
- Consumes: sandbox `POST /run` and `GET /status` via `SANDBOX_HOST` env var
- Produces:
  - `GET /api/snippets` → `[{"id": str, "title": str, "description": str, "code": str}]`
  - `POST /api/run` body: `{"session_id": str, "code": str}` → sandbox response pass-through
  - `GET /api/status/{session_id}` → sandbox status pass-through
  - `GET /` → serves `static/index.html`

- [ ] **Step 1: Create `playground/app/snippets.py`**

```python
SNIPPETS = [
    {
        "id": "hello",
        "title": "Hello World",
        "description": "Sanity check — instant output",
        "code": 'print("Hello from your sandbox!")\nprint("Sandbox is isolated and ready.")',
    },
    {
        "id": "fibonacci",
        "title": "Fibonacci",
        "description": "Compute with memoization",
        "code": (
            "from functools import lru_cache\n\n"
            "@lru_cache(maxsize=None)\n"
            "def fib(n):\n"
            "    return n if n < 2 else fib(n-1) + fib(n-2)\n\n"
            "for i in range(15):\n"
            "    print(f'fib({i}) = {fib(i)}')"
        ),
    },
    {
        "id": "files",
        "title": "Write & Read Files",
        "description": "Files persist in your sandbox workspace",
        "code": (
            "import os\n\n"
            "# Write three files\n"
            "for i in range(1, 4):\n"
            "    with open(f'note_{i}.txt', 'w') as f:\n"
            "        f.write(f'Note {i}: sandbox file storage works!\\n')\n\n"
            "# Read them back\n"
            "for name in sorted(os.listdir('.')):\n"
            "    with open(name) as f:\n"
            "        print(f'{name}: {f.read().strip()}')"
        ),
    },
    {
        "id": "fetch",
        "title": "Fetch a URL",
        "description": "Network egress from inside the sandbox",
        "code": (
            "import urllib.request\n\n"
            "url = 'http://example.com'\n"
            "with urllib.request.urlopen(url, timeout=8) as r:\n"
            "    body = r.read().decode()\n"
            "    lines = [l for l in body.splitlines() if l.strip()][:6]\n"
            "    print(f'Status: {r.status}')\n"
            "    print('First 6 non-empty lines:')\n"
            "    for line in lines:\n"
            "        print(' ', line)"
        ),
    },
    {
        "id": "pip_install",
        "title": "Install a Package",
        "description": "pip install works — packages persist while sandbox is alive",
        "code": (
            "import subprocess, sys\n\n"
            "print('Installing cowsay...')\n"
            "result = subprocess.run(\n"
            "    [sys.executable, '-m', 'pip', 'install', 'cowsay', '-q'],\n"
            "    capture_output=True, text=True\n"
            ")\n"
            "print(result.stdout or '(installed)')\n\n"
            "import cowsay\n"
            "cowsay.cow('Hello from a freshly installed package!')"
        ),
    },
    {
        "id": "data",
        "title": "Data Processing",
        "description": "Parse CSV, compute stats, write result file",
        "code": (
            "import csv, io, statistics\n\n"
            "raw = '''name,score\\nAlice,92\\nBob,87\\nCarol,95\\nDave,78\\nEve,91'''\n\n"
            "rows = list(csv.DictReader(io.StringIO(raw)))\n"
            "scores = [int(r['score']) for r in rows]\n"
            "stats = {\n"
            "    'count': len(scores),\n"
            "    'mean': statistics.mean(scores),\n"
            "    'median': statistics.median(scores),\n"
            "    'stdev': round(statistics.stdev(scores), 2),\n"
            "    'min': min(scores),\n"
            "    'max': max(scores),\n"
            "}\n"
            "for k, v in stats.items():\n"
            "    print(f'{k:8}: {v}')\n\n"
            "with open('stats.csv', 'w') as f:\n"
            "    f.write(','.join(stats.keys()) + '\\n')\n"
            "    f.write(','.join(str(v) for v in stats.values()) + '\\n')\n"
            "print('\\nWrote stats.csv to workspace')"
        ),
    },
]
```

- [ ] **Step 2: Create `playground/app/main.py`**

```python
import os
import time
from pathlib import Path

import httpx
import jwt
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
```

- [ ] **Step 3: Create `playground/app/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY main.py snippets.py ./
COPY static/ static/
RUN pip install fastapi uvicorn httpx pyjwt --no-cache-dir
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 4: Smoke-test the service against the live sandbox**

Start sandbox (from Task 1) and service together:
```bash
# Terminal 1
cd playground/sandbox
JWT_SECRET=testsecret uvicorn runner:app --port 8080

# Terminal 2 — create a minimal static/index.html first so StaticFiles doesn't error
mkdir -p playground/app/static
echo "<html><body>placeholder</body></html>" > playground/app/static/index.html
echo "" > playground/app/static/app.js

cd playground/app
JWT_SECRET=testsecret SANDBOX_HOST=localhost:8080 uvicorn main:app --port 8000

# Terminal 3
curl -s http://localhost:8000/api/snippets | python3 -m json.tool | head -20

curl -s -X POST http://localhost:8000/api/run \
  -H "Content-Type: application/json" \
  -d '{"session_id":"alice","code":"print(42)"}' | python3 -m json.tool

curl -s http://localhost:8000/api/status/alice | python3 -m json.tool

# Test empty session_id
curl -s -X POST http://localhost:8000/api/run \
  -H "Content-Type: application/json" \
  -d '{"session_id":"","code":"print(1)"}' | python3 -m json.tool
# Expected: 400
```

- [ ] **Step 5: Commit**

```bash
git add playground/app/main.py playground/app/snippets.py playground/app/Dockerfile
git commit -m "feat(app): add FastAPI service with snippet list and sandbox proxy"
```

---

## Task 3: SPA (`app/static/index.html` + `app/static/app.js`)

**Files:**
- Create: `playground/app/static/index.html`
- Create: `playground/app/static/app.js`

**Interfaces:**
- Consumes: `GET /api/snippets`, `POST /api/run`, `GET /api/status/{session_id}`
- localStorage keys: `ch_session_id` (active session), `ch_sessions` (JSON array of `{id, label, created_at}`)

- [ ] **Step 1: Create `playground/app/static/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Container Hosting Playground</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --accent: #58a6ff; --green: #3fb950; --red: #f85149;
    --text: #e6edf3; --muted: #8b949e; --font: 'Segoe UI', system-ui, sans-serif;
    --mono: 'Cascadia Code', 'Fira Code', monospace;
  }
  body { background: var(--bg); color: var(--text); font-family: var(--font); height: 100vh; display: flex; flex-direction: column; }
  header { padding: 12px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
  header h1 { font-size: 1rem; font-weight: 600; color: var(--accent); }
  header .badge { font-size: 0.75rem; background: #388bfd26; border: 1px solid #388bfd66; color: var(--accent); padding: 2px 8px; border-radius: 12px; }
  #sandbox-badge { font-size: 0.75rem; color: var(--muted); margin-left: auto; }
  .layout { display: grid; grid-template-columns: 220px 1fr 1fr; flex: 1; overflow: hidden; }
  /* Sidebar */
  .sidebar { border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
  .sidebar h2 { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); padding: 12px 14px 6px; }
  #session-list { flex: 1; overflow-y: auto; }
  .session-item { padding: 7px 14px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; border-radius: 0; transition: background 0.1s; }
  .session-item:hover { background: #ffffff0a; }
  .session-item.active { background: #388bfd18; color: var(--accent); }
  .session-item .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); flex-shrink: 0; }
  .session-item.active .dot { background: var(--green); }
  .session-item .meta { margin-left: auto; font-size: 0.7rem; color: var(--muted); }
  .sidebar-footer { padding: 10px 14px; border-top: 1px solid var(--border); display: flex; gap: 6px; }
  #new-session-input { flex: 1; background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 5px 8px; border-radius: 4px; font-size: 0.8rem; font-family: var(--mono); }
  #new-session-btn { background: #238636; border: none; color: #fff; padding: 5px 10px; border-radius: 4px; cursor: pointer; font-size: 0.8rem; font-weight: 600; }
  #new-session-btn:hover { background: #2ea043; }
  /* Editor panel */
  .editor-panel { border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
  #snippet-tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 10px 14px; border-bottom: 1px solid var(--border); }
  .snippet-tab { background: var(--surface); border: 1px solid var(--border); color: var(--muted); padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 0.78rem; transition: all 0.1s; }
  .snippet-tab:hover { border-color: var(--accent); color: var(--text); }
  .snippet-tab.active { border-color: var(--accent); color: var(--accent); background: #388bfd18; }
  #code-editor { flex: 1; resize: none; background: var(--surface); border: none; color: var(--text); font-family: var(--mono); font-size: 0.85rem; padding: 14px; outline: none; line-height: 1.6; }
  .editor-footer { padding: 10px 14px; border-top: 1px solid var(--border); display: flex; align-items: center; gap: 10px; }
  #run-btn { background: #238636; border: none; color: #fff; padding: 7px 20px; border-radius: 4px; cursor: pointer; font-size: 0.9rem; font-weight: 600; display: flex; align-items: center; gap: 6px; }
  #run-btn:hover { background: #2ea043; }
  #run-btn:disabled { background: #1f2e1f; color: var(--muted); cursor: not-allowed; }
  #run-hint { font-size: 0.75rem; color: var(--muted); }
  /* Output panel */
  .output-panel { display: flex; flex-direction: column; overflow: hidden; }
  .output-panel h2 { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); padding: 12px 14px 6px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
  #output-stdout { flex: 1; overflow-y: auto; padding: 14px; font-family: var(--mono); font-size: 0.82rem; line-height: 1.6; white-space: pre-wrap; word-break: break-all; }
  #output-stdout .out { color: var(--text); }
  #output-stdout .err { color: var(--red); }
  #output-stdout .meta { color: var(--muted); font-style: italic; margin-bottom: 8px; }
  #output-stdout .empty { color: var(--muted); }
  #files-section { border-top: 1px solid var(--border); padding: 10px 14px; flex-shrink: 0; max-height: 160px; overflow-y: auto; }
  #files-section h3 { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 6px; }
  .file-item { font-size: 0.8rem; font-family: var(--mono); color: #79c0ff; padding: 2px 0; display: flex; gap: 10px; }
  .file-item .size { color: var(--muted); }
  /* Responsive */
  @media (max-width: 900px) {
    .layout { grid-template-columns: 1fr; grid-template-rows: auto 1fr 1fr; }
    .sidebar { max-height: 200px; border-right: none; border-bottom: 1px solid var(--border); }
    .editor-panel { border-right: none; border-bottom: 1px solid var(--border); }
  }
</style>
</head>
<body>
<header>
  <h1>Container Hosting Playground</h1>
  <span class="badge">two assets · one YAML · zero Kubernetes</span>
  <span id="sandbox-badge">sandbox: — · idle</span>
</header>
<div class="layout">
  <aside class="sidebar">
    <h2>Sessions</h2>
    <div id="session-list"></div>
    <div class="sidebar-footer">
      <input id="new-session-input" type="text" placeholder="session-id" autocomplete="off">
      <button id="new-session-btn" title="Create session">+</button>
    </div>
  </aside>
  <section class="editor-panel">
    <div id="snippet-tabs"></div>
    <textarea id="code-editor" spellcheck="false"></textarea>
    <div class="editor-footer">
      <button id="run-btn">▶ Run</button>
      <span id="run-hint">Select a snippet or write your own Python</span>
    </div>
  </section>
  <section class="output-panel">
    <h2>Output</h2>
    <div id="output-stdout"><span class="empty">Run a snippet to see output here.</span></div>
    <div id="files-section">
      <h3>/workspace files</h3>
      <div id="files-list"><span style="color:var(--muted);font-size:0.8rem">—</span></div>
    </div>
  </section>
</div>
<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `playground/app/static/app.js`**

```javascript
// Session management
function loadSessions() {
  try { return JSON.parse(localStorage.getItem('ch_sessions') || '[]'); } catch { return []; }
}
function saveSessions(sessions) { localStorage.setItem('ch_sessions', JSON.stringify(sessions)); }
function activeSession() { return localStorage.getItem('ch_session_id') || ''; }
function setActive(id) { localStorage.setItem('ch_session_id', id); }

function uuidv4() {
  return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16));
}

// Ensure at least one session exists on first load
(function initFirstSession() {
  const sessions = loadSessions();
  if (!sessions.length) {
    const id = uuidv4();
    sessions.push({ id, label: id.slice(0, 8), created_at: Date.now() });
    saveSessions(sessions);
    setActive(id);
  } else if (!activeSession()) {
    setActive(sessions[0].id);
  }
})();

// Snippets
let snippets = [];

async function loadSnippets() {
  const resp = await fetch('/api/snippets');
  snippets = await resp.json();
  renderSnippetTabs();
  if (snippets.length) selectSnippet(snippets[0]);
}

function renderSnippetTabs() {
  const container = document.getElementById('snippet-tabs');
  container.innerHTML = '';
  snippets.forEach(s => {
    const btn = document.createElement('button');
    btn.className = 'snippet-tab';
    btn.textContent = s.title;
    btn.title = s.description;
    btn.onclick = () => selectSnippet(s);
    container.appendChild(btn);
  });
}

function selectSnippet(snippet) {
  document.querySelectorAll('.snippet-tab').forEach((btn, i) => {
    btn.classList.toggle('active', snippets[i]?.id === snippet.id);
  });
  document.getElementById('code-editor').value = snippet.code;
}

// Session UI
function renderSessions() {
  const sessions = loadSessions();
  const active = activeSession();
  const container = document.getElementById('session-list');
  container.innerHTML = '';
  sessions.forEach(s => {
    const div = document.createElement('div');
    div.className = 'session-item' + (s.id === active ? ' active' : '');
    div.innerHTML = `<span class="dot"></span><span>${escHtml(s.label || s.id.slice(0,12))}</span><span class="meta" id="meta-${escAttr(s.id)}"></span>`;
    div.onclick = () => switchSession(s.id);
    container.appendChild(div);
  });
  updateBadge();
  refreshAllMeta(sessions, active);
}

async function refreshAllMeta(sessions, active) {
  for (const s of sessions) {
    refreshMeta(s.id, s.id === active);
  }
}

async function refreshMeta(sessionId, isActive) {
  const el = document.getElementById(`meta-${escAttr(sessionId)}`);
  if (!el) return;
  try {
    const resp = await fetch(`/api/status/${encodeURIComponent(sessionId)}`);
    const data = await resp.json();
    const count = (data.files || []).length;
    el.textContent = count ? `${count} file${count !== 1 ? 's' : ''}` : '';
    if (isActive) renderFiles(data.files || []);
  } catch {}
}

function switchSession(id) {
  setActive(id);
  renderSessions();
  document.getElementById('output-stdout').innerHTML = '<span class="empty">Switched session. Run a snippet to see output.</span>';
  renderFiles([]);
}

function addSession(id) {
  id = id.trim();
  if (!id) return;
  const sessions = loadSessions();
  if (sessions.find(s => s.id === id)) { switchSession(id); return; }
  sessions.push({ id, label: id.slice(0, 20), created_at: Date.now() });
  saveSessions(sessions);
  setActive(id);
  renderSessions();
}

// Run code
document.getElementById('run-btn').onclick = async () => {
  const code = document.getElementById('code-editor').value;
  const sessionId = activeSession();
  if (!code.trim()) return;
  const btn = document.getElementById('run-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Running…';

  const out = document.getElementById('output-stdout');
  out.innerHTML = '<span class="meta">Running…</span>';

  try {
    const resp = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, code }),
    });
    const data = await resp.json();
    out.innerHTML = '';
    out.appendChild(metaLine(`Session: ${sessionId} · ${data.duration_ms}ms`));
    if (data.stdout) out.appendChild(outBlock(data.stdout, 'out'));
    if (data.stderr) out.appendChild(outBlock(data.stderr, 'err'));
    if (!data.stdout && !data.stderr) out.appendChild(outBlock('(no output)', 'empty'));
    renderFiles(data.files || []);
    refreshMeta(sessionId, true);
  } catch (e) {
    out.innerHTML = `<span class="err">Error: ${escHtml(String(e))}</span>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ Run';
  }
};

// File list
function renderFiles(files) {
  const el = document.getElementById('files-list');
  if (!files.length) {
    el.innerHTML = '<span style="color:var(--muted);font-size:0.8rem">—</span>';
    return;
  }
  el.innerHTML = files.map(f =>
    `<div class="file-item">📄 ${escHtml(f.name)}<span class="size">${fmtSize(f.size)}</span></div>`
  ).join('');
}

function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}kB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

// Badge
function updateBadge() {
  const id = activeSession();
  const sessions = loadSessions();
  const s = sessions.find(x => x.id === id);
  const label = s ? (s.label || id.slice(0, 12)) : id.slice(0, 12);
  document.getElementById('sandbox-badge').textContent = `sandbox: ${label}`;
}

// New session input
document.getElementById('new-session-input').value = uuidv4().slice(0, 8);
document.getElementById('new-session-btn').onclick = () => {
  const val = document.getElementById('new-session-input').value;
  addSession(val);
  document.getElementById('new-session-input').value = uuidv4().slice(0, 8);
};
document.getElementById('new-session-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('new-session-btn').click();
});

// Helpers
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function escAttr(s) { return String(s).replace(/[^a-zA-Z0-9_-]/g, '_'); }
function metaLine(text) {
  const span = document.createElement('span');
  span.className = 'meta';
  span.textContent = text + '\n';
  return span;
}
function outBlock(text, cls) {
  const span = document.createElement('span');
  span.className = cls;
  span.textContent = text;
  return span;
}

// Boot
loadSnippets().then(() => renderSessions());
```

- [ ] **Step 3: Open in browser and verify**

Start the service (with sandbox from Task 1 still running):
```bash
cd playground/app
JWT_SECRET=testsecret SANDBOX_HOST=localhost:8080 uvicorn main:app --port 8000
```
Open `http://localhost:8000` in a browser. Verify:
- Three-column layout renders correctly
- Snippet tabs appear across the top of the editor panel
- Clicking a tab populates the code editor
- "+" button adds a session with the pre-filled ID
- Clicking different sessions in the sidebar switches the active one
- "▶ Run" on Hello World shows output in the right panel
- Running "Write & Read Files" shows files in the `/workspace files` section
- Sessions sidebar shows file counts after running

- [ ] **Step 4: Commit**

```bash
git add playground/app/static/
git commit -m "feat(ui): add SPA with session switcher, snippet tabs, and output panel"
```

---

## Task 4: Deployment manifests (`solution.yaml`, `build-config.json`, `deploy.sh`)

**Files:**
- Create: `playground/solution.yaml`
- Create: `playground/build-config.json`
- Create: `playground/deploy.sh`
- Create: `playground/README.md`

**Interfaces:**
- Consumes: container-hosting REST API at `$CH_BASE_URL` with `$CH_TOKEN` and `$CH_PROJECT`
- Produces: deployed solution accessible at the URL printed by `deploy.sh`

- [ ] **Step 1: Create `playground/solution.yaml`**

```yaml
apiVersion: hosting.sap.com/v1alpha1
kind: SolutionDeployment
metadata:
  name: playground
  namespace: default
spec:
  solutionName: playground
  version: 1.0.0
  tenant: demo
  regions:
    - name: aws-eu-central-1
  assets:
    - id: app
      kind: service
      image: PLACEHOLDER_APP_IMAGE
      port: 8000
      env:
        - name: JWT_SECRET
          value: ch-playground-demo-secret
        - name: SANDBOX_HOST
          value: sandbox-sandbox-router:8080
      requires:
        - sandbox

    - id: sandbox
      kind: agent
      image: PLACEHOLDER_SANDBOX_IMAGE
      port: 8080
      env:
        - name: JWT_SECRET
          value: ch-playground-demo-secret
      sandboxing:
        tenantClaim: sub
        idleTTL: 1m
      network:
        egress:
          allowedHosts:
            - pypi.org
            - files.pythonhosted.org
            - example.com
          allowedPorts: [443, 80]
```

- [ ] **Step 2: Create `playground/build-config.json`**

The inline Dockerfiles must match exactly the ones in `app/Dockerfile` and `sandbox/Dockerfile`:

```json
{
  "assetTypeMappings": [
    {
      "assetType": "service",
      "dockerfile": "FROM python:3.12-slim\nWORKDIR /app\nCOPY main.py snippets.py ./\nCOPY static/ static/\nRUN pip install fastapi uvicorn httpx pyjwt --no-cache-dir\nCMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n"
    },
    {
      "assetType": "agent",
      "dockerfile": "FROM python:3.12-slim\nWORKDIR /app\nCOPY runner.py .\nRUN pip install fastapi uvicorn pyjwt --no-cache-dir\nCMD [\"uvicorn\", \"runner:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8080\"]\n"
    }
  ]
}
```

- [ ] **Step 3: Create `playground/deploy.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Required env vars
: "${CH_BASE_URL:?set CH_BASE_URL to the container-hosting API base URL}"
: "${CH_TOKEN:?set CH_TOKEN to your API token}"
: "${CH_PROJECT:?set CH_PROJECT to your project ID}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZIP_FILE="$(mktemp /tmp/playground-XXXXXX.zip)"
trap 'rm -f "$ZIP_FILE"' EXIT

echo "==> Packaging playground..."
(cd "$SCRIPT_DIR/.." && zip -r "$ZIP_FILE" playground/ -x "*.pyc" -x "*/__pycache__/*" -x "*.DS_Store")
echo "    ZIP: $ZIP_FILE ($(du -h "$ZIP_FILE" | cut -f1))"

echo "==> Uploading source..."
UPLOAD=$(curl -sf -X POST \
  -H "Authorization: Bearer $CH_TOKEN" \
  -F "file=@$ZIP_FILE" \
  -F "name=playground" \
  "$CH_BASE_URL/projects/$CH_PROJECT/sources")
SOURCE_NAME=$(echo "$UPLOAD" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")
echo "    Source name: $SOURCE_NAME"

echo "==> Waiting for build..."
while true; do
  STATUS_JSON=$(curl -sf \
    -H "Authorization: Bearer $CH_TOKEN" \
    "$CH_BASE_URL/projects/$CH_PROJECT/sources/$SOURCE_NAME")
  STATUS=$(echo "$STATUS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "    status: $STATUS"
  case "$STATUS" in
    ready) break ;;
    scan-failed|build-failed) echo "Build failed. Check source status."; exit 1 ;;
  esac
  sleep 5
done

IMAGES=$(echo "$STATUS_JSON" | python3 -c "import sys,json; imgs=json.load(sys.stdin).get('images',[]); [print(i) for i in imgs]")
echo "==> Built images:"
echo "$IMAGES"

# Expect exactly 2 images: service (index 0) and agent (index 1)
# Order matches assetTypeMappings in build-config.json: service first, agent second
APP_IMAGE=$(echo "$IMAGES" | sed -n '1p')
SANDBOX_IMAGE=$(echo "$IMAGES" | sed -n '2p')

if [[ -z "$APP_IMAGE" || -z "$SANDBOX_IMAGE" ]]; then
  echo "ERROR: expected 2 image refs, got: $IMAGES"
  echo "Check build-config.json assetTypeMappings order."
  exit 1
fi

echo "==> Patching solution.yaml with image refs..."
SOLUTION_YAML=$(sed \
  -e "s|PLACEHOLDER_APP_IMAGE|$APP_IMAGE|g" \
  -e "s|PLACEHOLDER_SANDBOX_IMAGE|$SANDBOX_IMAGE|g" \
  "$SCRIPT_DIR/solution.yaml")

echo "==> Deploying solution..."
DEPLOY=$(echo "$SOLUTION_YAML" | python3 -c "
import sys, json, yaml
spec = yaml.safe_load(sys.stdin)
print(json.dumps({'spec': spec['spec']}))
" | curl -sf -X PUT \
  -H "Authorization: Bearer $CH_TOKEN" \
  -H "Content-Type: application/json" \
  -d @- \
  "$CH_BASE_URL/projects/$CH_PROJECT/solutions/playground")

echo "==> Deploy submitted:"
echo "$DEPLOY" | python3 -m json.tool

echo ""
echo "Done! Monitor status:"
echo "  curl -H 'Authorization: Bearer \$CH_TOKEN' $CH_BASE_URL/projects/\$CH_PROJECT/solutions/playground/status"
```

Note: the `deploy.sh` uses `python3 -c "import yaml"` for YAML→JSON conversion. If pyyaml is unavailable, the script falls back gracefully (just submits the raw JSON spec). Adjust if needed.

Actually, simpler: convert the solution.yaml fields directly without pyyaml. Replace the deploy step with a direct JSON body built from the patched YAML using the existing solution.yaml structure. Here is the simplified version that avoids pyyaml:

```bash
# Replace the "Deploying solution..." section with:
echo "==> Deploying solution..."
curl -sf -X PUT \
  -H "Authorization: Bearer $CH_TOKEN" \
  -H "Content-Type: application/json" \
  "$CH_BASE_URL/projects/$CH_PROJECT/solutions/playground" \
  -d "$(echo "$SOLUTION_YAML" | python3 -c "
import sys, json
# Minimal YAML→JSON for the spec block only (no pyyaml needed for this shape)
import re
text = sys.stdin.read()
# Extract the spec block and re-encode as JSON via pyyaml if available, else error
try:
    import yaml
    doc = yaml.safe_load(text)
    print(json.dumps({'spec': doc['spec']}))
except ImportError:
    print('ERROR: pyyaml required for deploy.sh. Install with: pip install pyyaml', file=sys.stderr)
    sys.exit(1)
")" | python3 -m json.tool
```

Simpler still: pre-build the JSON spec as a template in deploy.sh using shell heredoc. Update `deploy.sh` to use a JSON-native approach:

Rewrite `deploy.sh` Step 3 above using a JSON heredoc that avoids YAML parsing:

```bash
echo "==> Deploying solution..."
curl -sf -X PUT \
  -H "Authorization: Bearer $CH_TOKEN" \
  -H "Content-Type: application/json" \
  "$CH_BASE_URL/projects/$CH_PROJECT/solutions/playground" \
  -d '{
  "spec": {
    "solutionName": "playground",
    "version": "1.0.0",
    "tenant": "demo",
    "regions": [{"name": "aws-eu-central-1"}],
    "assets": [
      {
        "id": "app", "kind": "service",
        "image": "'"$APP_IMAGE"'", "port": 8000,
        "env": [
          {"name": "JWT_SECRET", "value": "ch-playground-demo-secret"},
          {"name": "SANDBOX_HOST", "value": "sandbox-sandbox-router:8080"}
        ],
        "requires": ["sandbox"]
      },
      {
        "id": "sandbox", "kind": "agent",
        "image": "'"$SANDBOX_IMAGE"'", "port": 8080,
        "env": [{"name": "JWT_SECRET", "value": "ch-playground-demo-secret"}],
        "sandboxing": {"tenantClaim": "sub", "idleTTL": "1m"},
        "network": {"egress": {
          "allowedHosts": ["pypi.org", "files.pythonhosted.org", "example.com"],
          "allowedPorts": [443, 80]
        }}
      }
    ]
  }
}' | python3 -m json.tool
```

Use this final JSON-heredoc version of the deploy step (no pyyaml dependency). Write the complete `deploy.sh` using this approach.

- [ ] **Step 4: Make deploy.sh executable**

```bash
chmod +x playground/deploy.sh
```

- [ ] **Step 5: Create `playground/README.md`**

```markdown
# Playground — Container Hosting Demo

**Two assets. One YAML. Zero Kubernetes.**

A Python code playground where each user gets their own isolated sandbox.
Shows: per-user isolation, file persistence, package installation, ephemerality.

## Prerequisites

- Access to a container-hosting project (`CH_PROJECT`, `CH_TOKEN`, `CH_BASE_URL`)

## Deploy in 3 steps

\```bash
# 1. Set your credentials
export CH_BASE_URL=https://container-hosting.runtime.kyma.dev.sap
export CH_TOKEN=<your-api-token>
export CH_PROJECT=<your-project-id>

# 2. Build and deploy
cd playground
./deploy.sh

# 3. Open the URL printed by deploy.sh
\```

## Demo script

1. Open the URL — click **Hello World** → **▶ Run**
2. Click **Write & Read Files** → see files appear in the workspace panel
3. Open an incognito tab → click **+** → name it `bob` → run same snippet
4. Switch back to original tab (`alice`) — files still there, completely isolated
5. Wait 1 minute (idleTTL) → refresh `bob` tab → workspace is empty
6. Show `solution.yaml` — two assets, done

## Local development

\```bash
# Terminal 1 — sandbox
cd sandbox && JWT_SECRET=dev uvicorn runner:app --port 8080

# Terminal 2 — service
cd app && JWT_SECRET=dev SANDBOX_HOST=localhost:8080 uvicorn main:app --port 8000

# Open http://localhost:8000
\```
```

- [ ] **Step 6: Commit**

```bash
git add playground/solution.yaml playground/build-config.json playground/deploy.sh playground/README.md
git commit -m "feat(deploy): add solution.yaml, build-config.json, and deploy.sh"
```

---

## Task 5: End-to-end deploy and smoke test

**Files:** No new files — validation only.

- [ ] **Step 1: Set credentials and run deploy.sh**

```bash
export CH_BASE_URL=https://container-hosting.runtime.kyma.dev.sap
export CH_TOKEN=<your-api-token>
export CH_PROJECT=<your-project-id>
cd playground
./deploy.sh
```

Expected output:
```
==> Packaging playground...
==> Uploading source...
    Source name: playground
==> Waiting for build...
    status: pending
    status: scanning
    status: building
    status: ready
==> Built images:
<registry>/playground-app:...
<registry>/playground-sandbox:...
==> Patching solution.yaml with image refs...
==> Deploying solution...
{ "id": "...", "status": "pending", ... }
```

If `images` array has 0 or 1 entries, the build-config.json `assetTypeMappings` order or asset types may not match. Check the source status for error details:
```bash
curl -H "Authorization: Bearer $CH_TOKEN" \
  "$CH_BASE_URL/projects/$CH_PROJECT/sources/playground" | python3 -m json.tool
```

- [ ] **Step 2: Monitor solution status until ready**

```bash
watch -n 5 "curl -sf -H 'Authorization: Bearer $CH_TOKEN' \
  $CH_BASE_URL/projects/$CH_PROJECT/solutions/playground/status | python3 -m json.tool"
```

Wait for `"status": "ready"`. Retrieve the public URL from the status response.

- [ ] **Step 3: Run the demo script**

Follow the demo script from the README:
1. Open the URL — verify three-column layout loads
2. Click Hello World → Run → verify output appears
3. Click Write & Read Files → Run → verify 3 files appear in workspace section
4. Open incognito tab → create session `bob` → run same snippet → verify different files
5. Verify `alice` tab still shows its files
6. Wait 1 minute → refresh → verify `bob` workspace is empty

- [ ] **Step 4: Verify pip install snippet**

Run the **Install a Package** snippet. Expected:
- stdout shows cowsay ASCII art
- No "connection refused" or "network unreachable" errors
- If `pip install` fails: add missing hosts to `network.egress.allowedHosts` in `solution.yaml` and redeploy

- [ ] **Step 5: Final commit**

```bash
git add -p   # review any last-minute fixes made during e2e
git commit -m "fix(deploy): e2e validated — playground fully operational"
git push
```
