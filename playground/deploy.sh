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
(cd "$SCRIPT_DIR/.." && zip -r "$ZIP_FILE" playground/ \
  -x "*.pyc" -x "*/__pycache__/*" -x "*.DS_Store" -x "*.git*")
echo "    ZIP: $(du -h "$ZIP_FILE" | cut -f1)"

echo "==> Uploading source..."
UPLOAD=$(curl -sf -X POST \
  -H "Authorization: Bearer $CH_TOKEN" \
  -F "file=@$ZIP_FILE" \
  -F "name=playground" \
  "$CH_BASE_URL/projects/$CH_PROJECT/sources")
SOURCE_NAME=$(echo "$UPLOAD" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")
echo "    Source name: $SOURCE_NAME"

echo "==> Waiting for build (status: pending → scanning → building → ready)..."
while true; do
  STATUS_JSON=$(curl -sf \
    -H "Authorization: Bearer $CH_TOKEN" \
    "$CH_BASE_URL/projects/$CH_PROJECT/sources/$SOURCE_NAME")
  STATUS=$(echo "$STATUS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  printf "    status: %s\n" "$STATUS"
  case "$STATUS" in
    ready) break ;;
    scan-failed|build-failed)
      echo "ERROR: build failed. Full response:"
      echo "$STATUS_JSON" | python3 -m json.tool
      exit 1
      ;;
  esac
  sleep 5
done

# images[] is ordered by assetTypeMappings: service (index 0), agent (index 1)
APP_IMAGE=$(echo "$STATUS_JSON" | python3 -c "import sys,json; imgs=json.load(sys.stdin).get('images',[]); print(imgs[0] if imgs else '')")
SANDBOX_IMAGE=$(echo "$STATUS_JSON" | python3 -c "import sys,json; imgs=json.load(sys.stdin).get('images',[]); print(imgs[1] if len(imgs)>1 else '')")

if [[ -z "$APP_IMAGE" || -z "$SANDBOX_IMAGE" ]]; then
  echo "ERROR: expected 2 image refs. Got:"
  echo "$STATUS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('images',[]))"
  echo ""
  echo "Check build-config.json assetTypeMappings — one entry per asset type required."
  exit 1
fi

echo "==> Built images:"
echo "    app:     $APP_IMAGE"
echo "    sandbox: $SANDBOX_IMAGE"

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

echo ""
echo "==> Done! Monitor solution status:"
echo "    curl -H 'Authorization: Bearer \$CH_TOKEN' \\"
echo "      $CH_BASE_URL/projects/\$CH_PROJECT/solutions/playground/status"
