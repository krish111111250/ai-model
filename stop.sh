#!/bin/bash
# Stop the Krish AI services started by ./start.sh
# Use --all to also stop Ollama and MongoDB (they are shared with other apps).

stop_port() {
  local port="$1" name="$2"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null)"

  if [ -z "$pids" ]; then
    echo "   $name: not running"
    return
  fi

  kill $pids 2>/dev/null
  for _ in $(seq 1 10); do
    lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 1
  done
  lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && kill -9 $pids 2>/dev/null

  echo "   $name: stopped"
}

echo "🛑 Stopping Krish AI"
stop_port 5173 Frontend
stop_port 8001 Gateway
stop_port 8000 Engine

# Hand the model memory back immediately instead of waiting for the idle
# timeout - on a small Mac that is 3+ GB freed the moment you stop the app.
if command -v ollama >/dev/null 2>&1; then
  for model in $(ollama ps 2>/dev/null | awk 'NR>1 {print $1}'); do
    ollama stop "$model" >/dev/null 2>&1 && echo "   unloaded model: $model"
  done
fi

if [ "$1" = "--all" ]; then
  stop_port 27017 MongoDB
  stop_port 11434 Ollama
else
  echo "   (Ollama and MongoDB left running - use ./stop.sh --all to stop them too)"
fi
