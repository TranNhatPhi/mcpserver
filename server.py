"""General-purpose MCP server: file, web, and shell tools.

Transports
----------
Local (Claude Desktop / Claude Code), stdio — default:
    .venv/bin/python server.py

Remote (claude.ai custom connector), Streamable HTTP:
    MCP_TRANSPORT=streamable-http .venv/bin/python server.py
    # then expose http://127.0.0.1:8000/mcp via a public HTTPS tunnel

Environment variables
---------------------
    MCP_TRANSPORT     "stdio" (default) | "streamable-http"
    MCP_HOST          host to bind for HTTP (default 127.0.0.1)
    MCP_PORT          port to bind for HTTP (default 8000)
    MCP_BASE_DIR      sandbox root: confine all file paths to this directory
    MCP_READ_ONLY     "1" = only read tools (read_file/list_directory/
                      search_files + file:// resource). Recommended when the
                      server is reachable over a network. Default "0".
    MCP_ENABLE_EXEC   "1" (default) registers run_command in full mode; "0"
                      disables it. Ignored when MCP_READ_ONLY=1.
"""

import os
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import prompts
import resources
from tools import drive_tools, exec_tools, file_tools, image_tools, logo_tools, pdf_tools, s3_tools, web_tools

HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_PORT", "8000"))
TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")
READ_ONLY = os.environ.get("MCP_READ_ONLY", "0") == "1"
ENABLE_EXEC = os.environ.get("MCP_ENABLE_EXEC", "1") == "1"
# Public HTTPS URL of this server (e.g. the cloudflared tunnel). When set, OAuth
# is enabled so the claude.ai web custom connector can register and sign in.
PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", "").rstrip("/")
# Set MCP_DISABLE_OAUTH=1 to bypass OAuth entirely (claude.ai web will not work,
# but Claude Desktop / Claude Code stdio work fine without OAuth).
DISABLE_OAUTH = os.environ.get("MCP_DISABLE_OAUTH", "0") == "1"

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
    allowed_hosts=["*"],
    allowed_origins=["*"],
)

# Raise anyio's thread limiter so 100 concurrent sync-tool calls don't queue behind
# the default of 40. Sync MCP tools run in anyio's thread pool; without this, the
# 41st concurrent request stalls until a slot frees up.
THREAD_LIMITER_TOKENS = int(os.environ.get("MCP_THREAD_LIMIT", "120"))


@asynccontextmanager
async def _lifespan(app):
    import anyio
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = THREAD_LIMITER_TOKENS
    yield

# Enable OAuth only when a public URL is known and OAuth is not explicitly disabled.
auth_kwargs = {}
if PUBLIC_URL and not DISABLE_OAUTH:
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions

    from auth_provider import SimpleOAuthProvider

    auth_kwargs = dict(
        auth_server_provider=SimpleOAuthProvider(),
        auth=AuthSettings(
            issuer_url=PUBLIC_URL,
            resource_server_url=f"{PUBLIC_URL}/mcp",
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                default_scopes=["mcp"],
            ),
            required_scopes=[],
        ),
    )

mcp = FastMCP(
    "general-tools",
    host=HOST,
    port=PORT,
    transport_security=transport_security,
    lifespan=_lifespan,
    **auth_kwargs,
)

# --- MinIO / S3 tools (opt-in via MCP_S3_ENABLED=1) ---
# When S3 is enabled, all data lives in MinIO — use s3_* tools exclusively.
# When S3 is disabled, fall back to local filesystem tools.
S3_ENABLED = os.environ.get("MCP_S3_ENABLED", "0") == "1"

if S3_ENABLED:
    mcp.add_tool(s3_tools.s3_list)
    mcp.add_tool(s3_tools.s3_directory_tree)
    mcp.add_tool(s3_tools.s3_find_files)
    mcp.add_tool(s3_tools.s3_read)
    mcp.add_tool(s3_tools.s3_read_lines)
    mcp.add_tool(s3_tools.s3_read_many)
    mcp.add_tool(s3_tools.s3_search)
    mcp.add_tool(s3_tools.s3_kb_outline)
    mcp.add_tool(s3_tools.s3_kb_stats)
    mcp.add_tool(s3_tools.s3_read_pdf)
    mcp.add_tool(s3_tools.s3_list_logos)
    mcp.add_tool(s3_tools.s3_get_logo)
else:
    mcp.add_tool(file_tools.read_file)
    mcp.add_tool(file_tools.list_directory)
    mcp.add_tool(file_tools.search_files)
    mcp.add_tool(file_tools.directory_tree)
    mcp.add_tool(file_tools.find_files)
    mcp.add_tool(file_tools.read_lines)
    mcp.add_tool(file_tools.read_many_files)
    mcp.add_tool(file_tools.kb_outline)
    mcp.add_tool(file_tools.kb_stats)
    mcp.add_tool(pdf_tools.read_pdf)
    mcp.add_tool(image_tools.read_image)
    mcp.add_tool(logo_tools.list_logos)
    mcp.add_tool(logo_tools.get_logo)

# --- Google Drive read tools (opt-in via MCP_DRIVE_ENABLED=1) ---
DRIVE_ENABLED = os.environ.get("MCP_DRIVE_ENABLED", "0") == "1"
if DRIVE_ENABLED and drive_tools.is_configured():
    mcp.add_tool(drive_tools.drive_list)
    mcp.add_tool(drive_tools.drive_search)
    mcp.add_tool(drive_tools.drive_read)

# --- Mutating / powerful tools (only in full, non-read-only mode) ---
if not READ_ONLY:
    mcp.add_tool(file_tools.write_file)
    mcp.add_tool(file_tools.edit_file)
    mcp.add_tool(web_tools.fetch_url)
    mcp.add_tool(web_tools.http_request)
    if ENABLE_EXEC:
        # Arbitrary shell execution — never expose this over a network.
        mcp.add_tool(exec_tools.run_command)

# --- Resources & prompts ---
resources.register(mcp)
prompts.register(mcp)


# ASGI app for direct uvicorn invocation:
#   uvicorn server:app --host 0.0.0.0 --port 8000 --workers 4
# WARNING: --workers > 1 requires stateless OAuth (e.g. Redis) — in-memory
# SimpleOAuthProvider does not share state across worker processes.
if TRANSPORT == "streamable-http":
    try:
        app = mcp.streamable_http_app()
    except AttributeError:
        app = None  # older SDK — fall back to `python server.py`


if __name__ == "__main__":
    mode = "READ-ONLY" if READ_ONLY else "FULL"
    base = file_tools.BASE_DIR or "(unconfined)"
    auth = f"OAuth@{PUBLIC_URL}" if PUBLIC_URL else "none"
    print(f"[general-tools] transport={TRANSPORT} mode={mode} base_dir={base} auth={auth}")
    mcp.run(transport=TRANSPORT)
