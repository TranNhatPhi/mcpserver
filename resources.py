"""MCP resources: expose data that clients can browse/attach as context."""

import os

from tools.file_tools import MAX_READ_BYTES, _resolve


def register(mcp):
    @mcp.resource("file://{path}")
    def file_resource(path: str) -> str:
        """Return the text contents of a file (relative to the KB root)."""
        abs_path = _resolve(path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"Not a file: {path}")
        if os.path.getsize(abs_path) > MAX_READ_BYTES:
            raise ValueError(f"File too large: {path}")
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
