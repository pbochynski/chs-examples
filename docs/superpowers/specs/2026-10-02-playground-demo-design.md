# Playground Demo — Design Spec

**Date:** 2026-10-02  
**Repo:** github.tools.sap/container-hosting/examples  
**Path:** `playground/`

## Goal

A self-contained, visually attractive demo application that shows container-hosting's
key value to any audience — developers, platform engineers, PMs — in under 5 minutes.

**Hero message:** *Two assets, one YAML, production-grade isolation. Zero Kubernetes.*

The app is a Python code playground where each browser session gets its own isolated
sandbox. Users pick curated snippets, run them, see live output, and watch files persist
in their sandbox across runs. A session switcher lets the demo operator show multiple
independent sandboxes side-by-side.

## Architecture

```
Browser
  └─▶ service (FastAPI + SPA, kind: service)
           │  REQUIRES_SANDBOX_HOST (injected by container-hosting)
           └─▶ agent (Python runner, kind: agent)
                     sandboxing.tenantClaim: sub
                     → one container per session ID
```

Two assets. No external dependencies. No database. No message queue.

### `service` asset

- **Language:** Python 3.12, FastAPI + uvicorn
- **Static files:** SPA (vanilla HTML + JS + Prism.js for syntax highlight) bundled
  into the image under `/app/static/`, served via `StaticFiles` mount
- **Endpoints:**
  - `GET /` — serves `index.html`
  - `GET /api/snippets` — returns list of curated snippets (id, title, code)
  - `POST /api/run` — body: `{session_id, code}` — mints a short-lived JWT
    (`sub=session_id`, signed with `HS256`, secret from env `JWT_SECRET`),
    forwards `POST /run` to sandbox via `REQUIRES_SANDBOX_HOST`, returns output
  - `GET /api/status/{session_id}` — mints JWT, calls `GET /status` on sandbox,
    returns `{files: [...], idle_seconds: int}`
- **JWT secret:** random string, set as env var in `solution.yaml`. Not user-facing —
  only the service and sandbox need it.

### `agent` asset (sandbox runner)

- **Language:** Python 3.12-slim
- **Endpoints:**
  - `POST /run` — body: `{code}`, auth: `Authorization: Bearer <jwt>` — validates
    JWT (`sub` = session ID), executes code in a subprocess under `/workspace/<sub>/`,
    returns `{stdout, stderr, duration_ms, files}`
  - `GET /status` — same auth — returns `{files: [...], idle_seconds: int}`
- **Isolation:** container-hosting routes each unique `sub` to its own container via
  `sandboxing.tenantClaim: sub`. The sandbox itself validates the JWT to confirm the
  sub matches before executing.
- **Execution:** `subprocess.run(["python", "-c", code], cwd=/workspace/<sub>,
  timeout=10, capture_output=True)`. pip installs work because the container has pip
  and network egress.
- **Workspace:** `/workspace/<sub>/` created on first run, persisted while the
  sandbox container is alive.

## Session Model

Session ID lives in `localStorage` (`ch_session_id`). On first visit a UUID v4 is
generated. The UI stores a list of known sessions (`ch_sessions`) — each entry has
`{id, label, created_at}`.

**Session switcher panel** (left sidebar):
```
Sessions
────────────────────────
● alice         (active)
  bob            2 files
  demo-1         idle 8m
────────────────────────
[  new-session-id  ] [+]
```

- Pre-populated input with a UUID; user can overwrite with any string (e.g. `alice`)
- Switching session updates `ch_session_id` and refreshes status
- Same session ID on two machines = same sandbox (intentional, demo point)
- Sessions list is client-only; the service is stateless

## UI Design

Single-page app. Dark theme (`#0d1117` background, `#58a6ff` accent — GitHub dark palette).
Three-column layout:

```
┌──────────────┬──────────────────────────┬─────────────────────┐
│   Sessions   │       Code Editor        │      Output         │
│   (sidebar)  │                          │                     │
│              │  [ snippet picker tabs ] │  stdout / stderr    │
│  ● alice     │                          │  duration: 42ms     │
│    bob       │  <textarea + prism.js>   │                     │
│    demo-1    │                          │  /workspace files:  │
│              │          [▶ Run]         │  • hello.txt  12B   │
│  [new] [+]   │                          │  • data.csv   1.2kB │
└──────────────┴──────────────────────────┴─────────────────────┘
         sandbox badge: "sandbox: alice · idle 2m"
```

Responsive: on mobile the three columns stack vertically.

**No build step for the SPA.** Vanilla HTML/JS + Prism.js loaded from a CDN or
vendored as a single file. The SPA is a single `index.html` + `app.js` committed to
`app/static/`. This keeps the Dockerfile trivial and removes Node.js toolchain from
the build.

## Curated Snippets

Six snippets baked into the service. Designed to be interesting and self-explanatory:

| id | title | what it shows |
|----|-------|---------------|
| `hello` | Hello World | sanity check, instant output |
| `fibonacci` | Fibonacci | compute, memoization |
| `files` | Write & Read Files | `/workspace` persistence |
| `fetch` | Fetch a URL | network egress (`urllib`) |
| `pip_install` | Install a Package | `pip install cowsay`, shows pip works |
| `data` | Data Processing | parse CSV, print stats, write result file |

Each snippet is a plain string in `app/snippets.py`. No external file loading.

## Repo Layout

```
playground/
├── app/
│   ├── main.py            # FastAPI app
│   ├── snippets.py        # curated snippet definitions
│   ├── static/
│   │   ├── index.html
│   │   └── app.js
│   └── Dockerfile
├── sandbox/
│   ├── runner.py          # FastAPI runner
│   └── Dockerfile
├── build-config.json      # build pipeline config (service + agent Dockerfiles inline)
├── solution.yaml          # solutiondeploy.yaml — the hero artifact
├── deploy.sh              # wraps zip + POST /sources + wait + apply solution.yaml
└── README.md              # 3-step getting started
```

## `solution.yaml`

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
      image: <image-ref-from-build>   # filled by deploy.sh
      port: 8000
      env:
        - name: JWT_SECRET
          value: change-me-in-prod
      requires:
        - sandbox

    - id: sandbox
      kind: agent
      image: <image-ref-from-build>   # filled by deploy.sh
      port: 8080
      env:
        - name: JWT_SECRET
          value: change-me-in-prod
      sandboxing:
        tenantClaim: sub
        idleTTL: 10m
      network:
        egress:
          allowedHosts: ["pypi.org", "files.pythonhosted.org", "example.com"]
          allowedPorts: [443, 80]
```

## `build-config.json`

```json
{
  "assetTypeMappings": [
    {
      "assetType": "service",
      "dockerfile": "FROM python:3.12-slim\nWORKDIR /app\nCOPY app/ .\nRUN pip install fastapi uvicorn httpx pyjwt --no-cache-dir\nCMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n"
    },
    {
      "assetType": "agent",
      "dockerfile": "FROM python:3.12-slim\nWORKDIR /app\nCOPY sandbox/ .\nRUN pip install fastapi uvicorn pyjwt --no-cache-dir\nCMD [\"uvicorn\", \"runner:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8080\"]\n"
    }
  ]
}
```

## `deploy.sh` Flow

```
1. zip -r playground.zip playground/
2. POST /sources → returns {sourceId, operationId, imageRefs}
3. Poll GET /sources/{sourceId}/status until complete
4. sed image refs into solution.yaml
5. kubectl apply -f solution.yaml  (or REST API PUT /solutions/playground)
6. Print the public URL
```

Step 5 uses the container-hosting REST API (`PUT /projects/{projectId}/solutions/playground`)
so no `kubectl` is needed — the deploy script is pure `curl`.

## Demo Script

1. `./deploy.sh` — show the output, point out the two image refs and the URL
2. Open the URL in a browser — click **Hello World**, hit **Run** — instant output
3. Click **Write & Read Files** — run it, show files appearing in the output panel
4. Open incognito tab, create session `bob` — run same snippet — different files
5. Switch back to `alice` tab — files still there
6. Wait 10 min (or set `idleTTL: 1m` for demo) — refresh `bob` — workspace empty
7. `alice` still active — workspace intact
8. Show `solution.yaml` — two assets, one file, done

## Non-Goals

- Authentication / user accounts
- Persistent storage beyond sandbox lifetime
- Multi-language support (Python only)
- Production secrets management (JWT_SECRET in env is intentional simplicity for demo)

## Open Questions

- Build API: confirm single ZIP with `build-config.json` produces two separate image
  refs (one per asset type). Validate during implementation.
- `REQUIRES_SANDBOX_HOST` injection: confirm the env var name convention for asset id
  `sandbox` → `REQUIRES_SANDBOX_HOST` (not `REQUIRES_SANDBOX_HOST_PORT` etc.).
- Egress allowlist: confirm `pypi.org` + `files.pythonhosted.org` are sufficient for
  `pip install` inside the sandbox, or if more hosts are needed.
