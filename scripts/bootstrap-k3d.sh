#!/usr/bin/env bash
# Bootstrap a local k3d cluster and install Argo CD (Helm).
# Cost: $0 (runs on your machine via Docker). Idempotent-ish: safe to re-run.
#
# Windows: run from WSL2 (recommended) or Git Bash with Docker Desktop + WSL2 backend.
# Requires: docker, k3d, kubectl, helm on PATH.
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-grow-room-dev}"
ARGOCD_NS="${ARGOCD_NS:-argocd}"
ARGOCD_CHART_VERSION="${ARGOCD_CHART_VERSION:-7.7.12}"  # pin; bump deliberately

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need docker
need k3d
need kubectl
need helm

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not reachable. Start Docker Desktop / dockerd first." >&2
  exit 1
fi

if k3d cluster list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$CLUSTER_NAME"; then
  echo "==> k3d cluster '$CLUSTER_NAME' already exists"
else
  echo "==> Creating k3d cluster '$CLUSTER_NAME' (2 agents)"
  k3d cluster create "$CLUSTER_NAME" --agents 2
fi

kubectl cluster-info >/dev/null
echo "==> kube-context: $(kubectl config current-context)"

echo "==> Ensuring namespace $ARGOCD_NS"
kubectl get ns "$ARGOCD_NS" >/dev/null 2>&1 || kubectl create namespace "$ARGOCD_NS"

echo "==> Adding / updating argo Helm repo"
helm repo add argo https://argoproj.github.io/argo-helm 2>/dev/null || true
helm repo update argo

echo "==> Installing / upgrading Argo CD (chart ${ARGOCD_CHART_VERSION})"
helm upgrade --install argocd argo/argo-cd \
  --namespace "$ARGOCD_NS" \
  --version "$ARGOCD_CHART_VERSION" \
  --set configs.params."server\.insecure"=true \
  --wait \
  --timeout 10m

echo "==> Waiting for argocd-server"
kubectl -n "$ARGOCD_NS" rollout status deployment/argocd-server --timeout=300s

# Initial admin password (argocd-initial-admin-secret is deleted after first password change)
if kubectl -n "$ARGOCD_NS" get secret argocd-initial-admin-secret >/dev/null 2>&1; then
  ADMIN_PW="$(kubectl -n "$ARGOCD_NS" get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)"
  echo ""
  echo "Argo CD admin user: admin"
  echo "Argo CD initial password: ${ADMIN_PW}"
else
  echo ""
  echo "argocd-initial-admin-secret not found (password may already have been changed)."
fi

echo ""
echo "Port-forward the UI (leave this running in another terminal):"
echo "  kubectl -n ${ARGOCD_NS} port-forward svc/argocd-server 8080:443"
echo "Then open https://localhost:8080 (accept the self-signed cert if prompted)."
echo ""
echo "Next:"
echo "  1. Push charts/ and gitops/ to GitHub if you have not already."
echo "  2. kubectl apply -n argocd -f gitops/root-app.yaml"
echo "  3. Watch: kubectl -n argocd get applications"
echo ""
echo "Optional smoke WITHOUT Argo (from repo root):"
echo "  helm upgrade --install sensor ./charts/sensor-service -n grow-room --create-namespace -f charts/sensor-service/values-k3d.yaml"
