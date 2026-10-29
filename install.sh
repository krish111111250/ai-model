#!/bin/bash
# Krish AI on-premise installer (macOS / Linux).
#
# Builds the frontend, creates the Python environment the engine and the
# local gateway share, and writes backend/.env on first install. Safe to
# re-run: an existing venv and .env are kept, so it doubles as the upgrade
# step after pulling a new version.
#
# Downloads npm and pip packages. On an air-gapped machine run it once on a
# connected machine and copy the whole folder across, or point npm and pip at
# an internal mirror.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

fail() {
  echo "❌ $1" >&2
  exit 1
}

echo "Starting Krish AI On-Premise Setup..."

command -v npm >/dev/null 2>&1 || fail "npm not found. Install Node.js 20+ and re-run."
command -v python3 >/dev/null 2>&1 || fail "python3 not found. Install Python 3.10+ and re-run."

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || fail "Python 3.10 or newer is required (found $(python3 --version 2>&1))."

echo ""
echo "1/4 Frontend: installing packages and building"
cd "$ROOT/frontend"

# npm ci when there is a lockfile: exact versions, and it never rewrites the
# lockfile on a customer machine.
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi

npm run build
[ -f dist/index.html ] || fail "The frontend build produced no dist/index.html."

echo ""
echo "2/4 Backend: Python environment"
cd "$ROOT/backend"

if [ ! -x venv/bin/python ]; then
  python3 -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate

python -m pip install --upgrade pip
# One venv for both processes: start.sh runs the engine and the gateway from
# it, so the gateway's packages go in here too.
python -m pip install -r requirements.txt -r "$ROOT/requirements-client.txt"

echo ""
echo "3/4 Configuration"

if [ -f .env ]; then
  echo "   backend/.env exists - kept as it is"
else
  cp .env.example .env
  secret="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  # A temp file rather than sed -i, whose flags differ between macOS and Linux.
  # FRONTEND_URL moves to the engine's port: on-premise the engine serves the
  # app, and the template's 5173 is the Vite dev server.
  sed -e "s|^JWT_SECRET=.*|JWT_SECRET=$secret|" \
      -e "s|^FRONTEND_URL=.*|FRONTEND_URL=http://localhost:8000|" \
      .env > .env.tmp && mv .env.tmp .env
  chmod 600 .env
  echo "   wrote backend/.env with a new JWT_SECRET"
fi

echo ""
echo "4/4 Models"

# The answer model, in Ollama.
model="$(grep -E '^MAIN_LLM_MODEL=' .env | cut -d= -f2- || true)"
model="${model:-llama3.2:latest}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "   ⚠️  Ollama not found. Install it from https://ollama.com before starting."
elif ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$model"; then
  echo "   $model: present"
elif ollama pull "$model"; then
  echo "   $model: downloaded"
else
  echo "   ⚠️  $model is missing and could not be downloaded."
  echo "      Start Ollama (ollama serve) and re-run, or copy the model in"
  echo "      from a connected machine."
fi

# The gateway's own models: MiniLM for semantic search (Chroma's cache) and
# the cross-encoder reranker (Hugging Face's cache). Both download on first
# use, which an air-gapped machine cannot do, so they are fetched now. A
# failure here is not fatal - search falls back to keyword-only and
# reranking switches off.
reranker="$(grep -E '^KRISH_RERANKER_MODEL=' .env | cut -d= -f2- || true)"
KRISH_RERANKER_MODEL="${reranker:-cross-encoder/ms-marco-MiniLM-L-6-v2}" python - <<'PY_MODELS' \
  || echo "   ⚠️  Could not fetch the search models; run install again when online."
import os

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

DefaultEmbeddingFunction()(["warm up"])
print("   semantic search model: ready")

from sentence_transformers import CrossEncoder

CrossEncoder(os.environ["KRISH_RERANKER_MODEL"])
print(f"   reranker {os.environ['KRISH_RERANKER_MODEL']}: ready")
PY_MODELS

echo ""
echo "Installation complete! Run ./start.sh to launch the AI engine."
