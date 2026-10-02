#!/usr/bin/env bash
set -euo pipefail

# Required env vars
: "${CH_BASE_URL:?set CH_BASE_URL to the container-hosting API base URL}"
: "${CH_TOKEN:?set CH_TOKEN to your API token}"
: "${CH_PROJECT:?set CH_PROJECT to your project ID}"

# Image refs — override to test local builds
APP_IMAGE="${APP_IMAGE:-ghcr.io/pbochynski/chs-examples/playground-app:latest}"
SANDBOX_IMAGE="${SANDBOX_IMAGE:-ghcr.io/pbochynski/chs-examples/playground-sandbox:latest}"

echo "==> Deploying playground..."
echo "    app:     $APP_IMAGE"
echo "    sandbox: $SANDBOX_IMAGE"

RESPONSE=$(curl -sS -w '\n__HTTP_STATUS:%{http_code}' -X PUT \
  -H "Authorization: Bearer $CH_TOKEN" \
  -H "Content-Type: application/json" \
  "$CH_BASE_URL/projects/$CH_PROJECT/solutions/playground" \
  -d '{
  "spec": {
    "version": "1.0.0",
    "assets": [
      {
        "id": "app",
        "kind": "service",
        "image": "'"$APP_IMAGE"'",
        "port": 8000,
        "resources": {
          "requests": {"cpu": "50m", "memory": "64Mi"},
          "limits": {"cpu": "500m", "memory": "256Mi"}
        },
        "env": [
          {"name": "JWT_SECRET", "value": "ch-playground-demo-secret"},
          {"name": "SANDBOX_HOST", "value": "sandbox-sandbox-router:8080"}
        ],
        "requires": ["sandbox"]
      },
      {
        "id": "sandbox",
        "kind": "agent",
        "image": "'"$SANDBOX_IMAGE"'",
        "port": 8080,
        "resources": {
          "requests": {"cpu": "50m", "memory": "64Mi"},
          "limits": {"cpu": "500m", "memory": "256Mi"}
        },
        "env": [{"name": "JWT_SECRET", "value": "ch-playground-demo-secret"}],
        "sandboxing": {
          "tenantClaim": "sub",
          "idleTTL": "1m",
          "network": {
            "egress": [
              {"host": "pypi.org", "ports": [443]},
              {"host": "files.pythonhosted.org", "ports": [443]},
              {"host": "example.com", "ports": [443, 80]}
            ]
          }
        }
      }
    ]
  }
}')

HTTP_STATUS=$(echo "$RESPONSE" | grep -o '__HTTP_STATUS:[0-9]*' | cut -d: -f2)
BODY=$(echo "$RESPONSE" | sed 's/__HTTP_STATUS:[0-9]*$//')

if [[ "$HTTP_STATUS" != 2* ]]; then
  echo "ERROR: deploy failed (HTTP $HTTP_STATUS):"
  echo "$BODY"
  exit 1
fi

echo "$BODY" | python3 -m json.tool

echo ""
echo "==> Done! Monitor solution status:"
echo "    curl -H 'Authorization: Bearer \$CH_TOKEN' \\"
echo "      $CH_BASE_URL/projects/\$CH_PROJECT/solutions/playground/status"
