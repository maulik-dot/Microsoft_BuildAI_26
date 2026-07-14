#!/usr/bin/env bash
#
# Deploy Vayu to Azure Container Apps.
#
# Prereqs (one time):
#   1. Install Azure CLI:  https://aka.ms/azure-cli
#   2. az login                       # sign in (use the hackathon subscription)
#   3. export GOOGLE_API_KEY=...       # your Gemini key
#      export OPENROUTER_API_KEY=...   # your OpenRouter key
#
# Then just run:  ./deploy-azure.sh
#
# The image is BUILT IN THE CLOUD from the Dockerfile (ACR Tasks) — no local
# Docker required. Re-running redeploys the latest code.

set -euo pipefail

RG=${RG:-vayu-rg}
LOCATION=${LOCATION:-eastus}
APP=${APP:-vayu}

: "${GOOGLE_API_KEY:?Set GOOGLE_API_KEY (export GOOGLE_API_KEY=...)}"
: "${OPENROUTER_API_KEY:?Set OPENROUTER_API_KEY (export OPENROUTER_API_KEY=...)}"

echo "▶ Ensuring Container Apps extension + providers…"
az extension add --name containerapp --upgrade -y
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait

echo "▶ Resource group $RG ($LOCATION)…"
az group create --name "$RG" --location "$LOCATION" -o none

echo "▶ Building the Dockerfile in the cloud + deploying (first run creates the environment)…"
az containerapp up \
  --name "$APP" \
  --resource-group "$RG" \
  --location "$LOCATION" \
  --source . \
  --ingress external \
  --target-port 8000

echo "▶ Storing API keys as secrets…"
az containerapp secret set \
  --name "$APP" --resource-group "$RG" \
  --secrets google-key="$GOOGLE_API_KEY" openrouter-key="$OPENROUTER_API_KEY" -o none

echo "▶ Wiring env + resources: 2 vCPU / 4 GiB, single always-on replica…"
# min=max=1: one instance keeps the warm browser + background browse tasks alive,
# and guarantees the frontend polls the same replica that holds the task_store.
az containerapp update \
  --name "$APP" --resource-group "$RG" \
  --set-env-vars GOOGLE_API_KEY=secretref:google-key OPENROUTER_API_KEY=secretref:openrouter-key \
  --cpu 2 --memory 4Gi \
  --min-replicas 1 --max-replicas 1 -o none

FQDN=$(az containerapp show --name "$APP" --resource-group "$RG" \
  --query properties.configuration.ingress.fqdn -o tsv)

echo
echo "✅ Vayu is live at:  https://$FQDN"
echo "   Health check:     https://$FQDN/health"
echo "   Logs:  az containerapp logs show -n $APP -g $RG --follow"
