# Azure Deployment

InjectiveLens Agent Guard now deploys as a single Azure Container App.

The container serves:

- React frontend from the built `frontend/app/dist` bundle
- Python API under `/api/*`
- Agent protocol endpoints:
  - `/agent-registration.json`
  - `/.well-known/agent-card.json`
  - `/mcp/tools`
  - `/mcp`

This avoids the old split deployment where the frontend lived on Vercel and API calls were rewritten to Railway.

## Prerequisites

- Azure CLI
- Docker-compatible Azure Container Registry build support
- An Azure subscription

Sign in:

```bash
az login
az account set --subscription "<SUBSCRIPTION_ID_OR_NAME>"
```

## One-command Deploy

From the project root:

```bash
cd "InjectiveLens Agent Guard"

AZURE_LOCATION=eastus \
AZURE_RESOURCE_GROUP=rg-injectivelens-agent-guard \
AZURE_APP_NAME=injectivelens-agent-guard \
AZURE_ACR_NAME=<globally-unique-acr-name> \
./scripts/azure_deploy_containerapp.sh
```

The script will:

1. Create or reuse a resource group.
2. Create or reuse an Azure Container Registry.
3. Build the Docker image in ACR.
4. Create or reuse an Azure Container Apps environment.
5. Create or update the Container App.
6. Print the public HTTPS URL.

If `AZURE_ACR_NAME` is omitted, the script generates a registry name. Set it explicitly if you want repeatable updates.

## Runtime Environment

The Azure container uses these defaults:

```bash
HOST=0.0.0.0
PORT=8000
INJECTIVELENS_STATIC_DIR=/app/frontend-dist
INJECTIVELENS_STATE_FILE=/tmp/injectivelens_state.json
INJECTIVE_PROOF_RECORDER_MODE=external_tx
```

Optional live read-only Injective sources can be configured later:

```bash
az containerapp update \
  --name injectivelens-agent-guard \
  --resource-group rg-injectivelens-agent-guard \
  --set-env-vars \
    INJECTIVE_LCD_REST_URL="<lcd-url>" \
    INJECTIVE_MARKET_SNAPSHOT_URL="<market-url-template>" \
    INJECTIVE_POSITIONS_URL="<positions-url-template>"
```

After broadcasting a real Injective testnet assessment memo/event, attach the proof tx to the same app:

```bash
az containerapp update \
  --name injectivelens-agent-guard \
  --resource-group rg-injectivelens-agent-guard \
  --set-env-vars \
    INJECTIVE_PROOF_TX_HASH="<injective-testnet-tx-hash>" \
    INJECTIVE_PROOF_BLOCK_HEIGHT="<optional-block-height>"
```

Do not configure private keys, seed phrases, or real trading credentials for the hackathon P0 demo.

## Local Azure-shape Smoke Test

Build the frontend and run the same single-origin shape locally:

```bash
cd "InjectiveLens Agent Guard/frontend/app"
npm install
npm run build

cd ../..
PORT=8000 ./scripts/azure_start.sh
```

Open:

```text
http://127.0.0.1:8000/
```

Check:

- `/api/health`
- `/agent-registration.json`
- `/.well-known/agent-card.json`
- `/mcp/tools`

## Why This Fits Injective Nova

This deployment path strengthens the Microsoft/Azure part of the submission:

- The project has a concrete Azure runtime target.
- Frontend, API, and agent protocol are hosted together.
- MCP-compatible agent calls use the same origin as the product UI.
- The demo keeps the safety boundary: read-only, simulation-only, proof-only.
