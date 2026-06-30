#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

APP_NAME="${AZURE_APP_NAME:-injectivelens-agent-guard}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-${APP_NAME}}"
LOCATION="${AZURE_LOCATION:-eastus}"
ENVIRONMENT_NAME="${AZURE_CONTAINERAPPS_ENV:-${APP_NAME}-env}"
IMAGE_NAME="${AZURE_IMAGE_NAME:-${APP_NAME}}"
IMAGE_TAG="${AZURE_IMAGE_TAG:-latest}"

if ! command -v az >/dev/null 2>&1; then
  echo "Azure CLI is required. Install it, then run: az login" >&2
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  echo "Please sign in first: az login" >&2
  exit 1
fi

if [ -z "${AZURE_ACR_NAME:-}" ]; then
  suffix="$(date +%H%M%S)"
  AZURE_ACR_NAME="$(echo "${APP_NAME}acr${suffix}" | tr -cd '[:alnum:]' | cut -c1-50)"
  echo "AZURE_ACR_NAME was not set. Using generated registry name: ${AZURE_ACR_NAME}"
  echo "Set AZURE_ACR_NAME to reuse the same registry on future deploys."
fi

az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

if ! az acr show --name "$AZURE_ACR_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  az acr create \
    --name "$AZURE_ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --sku Basic \
    --admin-enabled true \
    --output none
fi

LOGIN_SERVER="$(az acr show --name "$AZURE_ACR_NAME" --resource-group "$RESOURCE_GROUP" --query loginServer -o tsv)"

az acr build \
  --registry "$AZURE_ACR_NAME" \
  --image "${IMAGE_NAME}:${IMAGE_TAG}" \
  --file Dockerfile \
  .

if ! az containerapp env show --name "$ENVIRONMENT_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  az containerapp env create \
    --name "$ENVIRONMENT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none
fi

REGISTRY_USERNAME="$(az acr credential show --name "$AZURE_ACR_NAME" --query username -o tsv)"
REGISTRY_PASSWORD="$(az acr credential show --name "$AZURE_ACR_NAME" --query 'passwords[0].value' -o tsv)"
IMAGE="${LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
ENV_VARS=(
  "INJECTIVE_PROOF_RECORDER_MODE=${INJECTIVE_PROOF_RECORDER_MODE:-external_tx}"
  "INJECTIVELENS_STATE_FILE=/tmp/injectivelens_state.json"
)

if [ -n "${INJECTIVE_PROOF_TX_HASH:-}" ]; then
  ENV_VARS+=("INJECTIVE_PROOF_TX_HASH=${INJECTIVE_PROOF_TX_HASH}")
fi
if [ -n "${INJECTIVE_PROOF_BLOCK_HEIGHT:-}" ]; then
  ENV_VARS+=("INJECTIVE_PROOF_BLOCK_HEIGHT=${INJECTIVE_PROOF_BLOCK_HEIGHT}")
fi
if [ -n "${INJECTIVE_PROOF_EXPLORER_URL:-}" ]; then
  ENV_VARS+=("INJECTIVE_PROOF_EXPLORER_URL=${INJECTIVE_PROOF_EXPLORER_URL}")
fi
if [ -n "${INJECTIVE_LCD_REST_URL:-}" ]; then
  ENV_VARS+=("INJECTIVE_LCD_REST_URL=${INJECTIVE_LCD_REST_URL}")
fi
if [ -n "${INJECTIVE_MARKET_SNAPSHOT_URL:-}" ]; then
  ENV_VARS+=("INJECTIVE_MARKET_SNAPSHOT_URL=${INJECTIVE_MARKET_SNAPSHOT_URL}")
fi
if [ -n "${INJECTIVE_POSITIONS_URL:-}" ]; then
  ENV_VARS+=("INJECTIVE_POSITIONS_URL=${INJECTIVE_POSITIONS_URL}")
fi
if [ -n "${INJECTIVE_READ_TIMEOUT_SECONDS:-}" ]; then
  ENV_VARS+=("INJECTIVE_READ_TIMEOUT_SECONDS=${INJECTIVE_READ_TIMEOUT_SECONDS}")
fi

if az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  az containerapp update \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --image "$IMAGE" \
    --set-env-vars "${ENV_VARS[@]}" \
    --output none
else
  az containerapp create \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENVIRONMENT_NAME" \
    --image "$IMAGE" \
    --target-port 8000 \
    --ingress external \
    --registry-server "$LOGIN_SERVER" \
    --registry-username "$REGISTRY_USERNAME" \
    --registry-password "$REGISTRY_PASSWORD" \
    --env-vars "${ENV_VARS[@]}" \
    --output none
fi

FQDN="$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)"

echo "Azure Container App deployed:"
echo "https://${FQDN}"
