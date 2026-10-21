#!/bin/bash
# Start Krish AI: Ollama, MongoDB, FastAPI backend, Vite frontend.
# Every service is detached, so it keeps running after this terminal (or a
# Claude Code session) closes. Logs go to ./logs. Stop everything with ./stop.sh

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOGS="$ROOT/logs"
MONGO_DBPATH="${MONGO_DBPATH:-$HOME/mongodb-data}"

mkdir -p "$LOGS"

# Keep the model in memory between questions, but not all day: on an 8GB Mac
# the chat and embedding models together hold ~3.4GB, which pushes everything
# else into swap and makes the whole machine crawl. 5 minutes covers a working
# session of questions; after that the RAM goes back to you.
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-5m}"

# One request at a time. Ollama otherwise reserves several copies of the
# context window, which is pure waste for a single-user local app.
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"

# A real connection test: lsof only shows processes owned by you, so a service
# started by another user (e.g. MongoDB under sudo) would look "down".
port_busy() {
  python3 -c "
import socket, sys
# Try every address localhost resolves to: Vite binds IPv6 only, so an
# IPv4-only check would miss it and start a second copy.
for family, socktype, proto, _, addr in socket.getaddrinfo('localhost', $1, 0, socket.SOCK_STREAM):
    s = socket.socket(family, socktype, proto)
    s.settimeout(1)
    if s.connect_ex(addr) == 0:
        sys.exit(0)
sys.exit(1)
" 2>/dev/null
}

start_detached() {
  local name="$1" workdir="$2"
  shift 2
  python3 - "$name" "$workdir" "$LOGS" "$@" <<'PY'
import os, subprocess, sys
name, workdir, logs, *cmd = sys.argv[1:]
log = open(os.path.join(logs, name + ".log"), "ab")
proc = subprocess.Popen(
    cmd, cwd=workdir, stdout=log, stderr=log,
    stdin=subprocess.DEVNULL, start_new_session=True,
)
print(f"   started (pid {proc.pid}), log: logs/{name}.log")
PY
}

wait_for_port() {
  local port="$1" name="$2"
  for _ in $(seq 1 40); do
    port_busy "$port" && { echo "   $name ready on port $port"; return 0; }
    sleep 1
  done
  echo "   ⚠️  $name did not come up on port $port - check logs/"
  return 1
}

echo "🚀 Starting Krish AI"

echo "1/5 Ollama"
if port_busy 11434; then
  echo "   already running"
else
  start_detached ollama "$ROOT" ollama serve
  wait_for_port 11434 Ollama
fi

echo "2/5 MongoDB  (data: $MONGO_DBPATH)"
if port_busy 27017; then
  echo "   already running"
else
  start_detached mongod "$ROOT" mongod --dbpath "$MONGO_DBPATH" --nounixsocket
  wait_for_port 27017 MongoDB
fi

echo "3/5 Engine (FastAPI, stateless)"
if port_busy 8000; then
  echo "   already running"
else
  start_detached backend "$ROOT/backend" \
    "$ROOT/backend/venv/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
  wait_for_port 8000 Backend
fi

echo "4/5 Local gateway (port 8001)"
if port_busy 8001; then
  echo "   already running"
else
  # The gateway holds the documents: it indexes and searches them on this
  # machine and sends the engine only the chunks a question matched.
  #
  # It is a separate process from the engine and reads no .env of its own, so
  # the reranker settings have to be handed to it here. Without this the
  # KRISH_RERANKER_* lines in backend/.env are documentation and nothing more.
  # A value already exported in this shell wins, so a one-off override still
  # works the way it did before the file became the default.
  while IFS='=' read -r key value; do
    [ -n "${!key+set}" ] || export "$key=$value"
  done < <(grep -E '^KRISH_[A-Z_]+=' "$ROOT/backend/.env" 2>/dev/null)
  start_detached gateway "$ROOT" \
    "$ROOT/backend/venv/bin/python" "$ROOT/client_gateway.py"
  wait_for_port 8001 Gateway
fi

echo "5/5 Frontend (Vite)"
if port_busy 5173; then
  echo "   already running"
else
  start_detached frontend "$ROOT/frontend" npm run dev
  wait_for_port 5173 Frontend
fi

# Load the model now so the first question is fast.
MODEL="$(grep -E '^MAIN_LLM_MODEL=' "$ROOT/backend/.env" 2>/dev/null | cut -d= -f2)"
MODEL="${MODEL:-llama3.2:latest}"
echo "🔥 Warming up model: $MODEL"
curl -s http://localhost:11434/api/generate \
  -d "{\"model\":\"$MODEL\",\"prompt\":\"hi\",\"stream\":false,\"keep_alive\":\"5m\"}" \
  >/dev/null 2>&1 && echo "   model loaded" || echo "   ⚠️  warm-up failed - check logs/ollama.log"

echo ""
echo "✅ Krish AI is running:  http://localhost:5173"
echo "   Gateway (your documents): http://localhost:8001  <- the UI talks to this"
echo "   Engine  (answers only):   http://localhost:8000"
echo "   Logs: $LOGS"
echo "   Stop everything with: ./stop.sh"
