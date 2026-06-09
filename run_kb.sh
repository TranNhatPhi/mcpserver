#!/usr/bin/env bash
#
# Run the MCP server in READ-ONLY mode, sandboxed to a knowledge-base folder,
# over Streamable HTTP — ready to expose to a claude.ai custom connector.
#
# Usage:
#   ./run_kb.sh /path/to/brainLNC
#   ./run_kb.sh /path/to/brainLNC 8001     # custom port (default 8000)
#
# Then, in another terminal, open a public HTTPS tunnel:
#   cloudflared tunnel --url http://127.0.0.1:8000
# and paste the printed https URL + "/mcp" into claude.ai's connector dialog.

set -euo pipefail

BASE_DIR="${1:-}"
PORT="${2:-8000}"

if [ -z "$BASE_DIR" ]; then
  echo "Usage: ./run_kb.sh /path/to/knowledge-base [port]" >&2
  exit 1
fi
if [ ! -d "$BASE_DIR" ]; then
  echo "Error: '$BASE_DIR' is not a directory" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export MCP_TRANSPORT=streamable-http
export MCP_READ_ONLY=1
export MCP_HOST=127.0.0.1
export MCP_PORT="$PORT"
export MCP_BASE_DIR="$BASE_DIR"

exec .venv/bin/python server.py
