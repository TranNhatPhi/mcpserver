#!/usr/bin/env bash
#
# One command to expose the knowledge base to the claude.ai WEB custom connector.
# Starts a cloudflared tunnel, learns its public HTTPS URL, then runs the MCP
# server in read-only + OAuth mode bound to that URL. Cleans up the tunnel on
# exit (Ctrl-C).
#
# Usage:
#   ./run_kb_oauth.sh /path/to/brainLNC
#   ./run_kb_oauth.sh /path/to/brainLNC 8001     # custom local port

set -euo pipefail

BASE_DIR="${1:-}"
PORT="${2:-8001}"

if [ -z "$BASE_DIR" ] || [ ! -d "$BASE_DIR" ]; then
  echo "Usage: ./run_kb_oauth.sh /path/to/knowledge-base [port]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

command -v cloudflared >/dev/null || { echo "cloudflared not found (brew install cloudflared)" >&2; exit 1; }

LOG="$(mktemp -t cloudflared.XXXX.log)"
echo "Starting cloudflared tunnel -> http://127.0.0.1:${PORT} ..."
cloudflared tunnel --url "http://127.0.0.1:${PORT}" >"$LOG" 2>&1 &
TUNNEL_PID=$!
trap 'echo; echo "Stopping tunnel ($TUNNEL_PID)"; kill $TUNNEL_PID 2>/dev/null || true' EXIT

PUBLIC_URL=""
for _ in $(seq 1 30); do
  PUBLIC_URL=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
  [ -n "$PUBLIC_URL" ] && break
  sleep 1
done
if [ -z "$PUBLIC_URL" ]; then
  echo "Could not obtain tunnel URL. Last log lines:" >&2
  tail -10 "$LOG" >&2
  exit 1
fi

echo
echo "=================================================================="
echo " Public URL : $PUBLIC_URL"
echo " Connector  : ${PUBLIC_URL}/mcp     <-- paste THIS into claude.ai"
echo "=================================================================="
echo

export MCP_TRANSPORT=streamable-http
export MCP_READ_ONLY=1
export MCP_HOST=127.0.0.1
export MCP_PORT="$PORT"
export MCP_BASE_DIR="$BASE_DIR"
export MCP_PUBLIC_URL="$PUBLIC_URL"

# NOTE: run (not exec) so the EXIT trap above still fires and stops cloudflared
# when the server stops.
.venv/bin/python server.py
