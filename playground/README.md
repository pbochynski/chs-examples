# Playground — Container Hosting Demo

![Build](https://github.com/pbochynski/chs-examples/actions/workflows/build.yml/badge.svg)

**Two assets. One YAML. Zero Kubernetes.**

A Python code playground where each user gets their own isolated sandbox.
Shows: per-user isolation, file persistence, package installation, ephemerality.

## Prerequisites

- Access to a container-hosting project (`CH_BASE_URL`, `CH_TOKEN`, `CH_PROJECT`)

## Deploy in 3 steps

```bash
# 1. Set your credentials
export CH_BASE_URL=https://container-hosting.runtime.kyma.dev.sap
export CH_TOKEN=<your-api-token>
export CH_PROJECT=<your-project-id>

# 2. Deploy
cd playground
./deploy.sh

# 3. Open the URL printed by deploy.sh
```

Images are built by GitHub Actions and published to
`ghcr.io/pbochynski/chs-examples/playground-app:latest` and
`ghcr.io/pbochynski/chs-examples/playground-sandbox:latest`.

To deploy a local build, override the image refs:

```bash
APP_IMAGE=<your-app-image> SANDBOX_IMAGE=<your-sandbox-image> ./deploy.sh
```

## Demo script

1. Open the URL — click **Hello World** → **▶ Run**
2. Click **Write & Read Files** → see files appear in the workspace panel
3. Open an incognito tab → click **+** → name it `bob` → run the same snippet
4. Switch back to your original session (`alice`) — files still there, completely isolated
5. Wait 1 minute (`idleTTL: 1m`) → `bob`'s workspace is empty
6. Show `solution.yaml` — two assets, one file, done

> **Demo tip:** The **Install a Package** snippet (`pip install cowsay`) may take 5–15s on a cold
> sandbox. Run it last, or run it once first to warm the package cache.

## Local development

```bash
# Terminal 1 — sandbox runner
cd sandbox
JWT_SECRET=dev WORKSPACE_ROOT=/tmp/playground-workspace uvicorn runner:app --port 8080

# Terminal 2 — service + SPA
cd app
JWT_SECRET=dev SANDBOX_HOST=localhost:8080 uvicorn main:app --port 8000

# Open http://localhost:8000
```

## Architecture

```
Browser
  └─▶ app (FastAPI + SPA, kind: service, port 8000)
           │  SANDBOX_HOST env var → sandbox:8080
           └─▶ sandbox (Python runner, kind: agent, port 8080)
                        sandboxing.tenantClaim: sub
                        → one container per session ID
```
