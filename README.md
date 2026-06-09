# mcpserver — knowledge-base MCP server

A Model Context Protocol (MCP) server, built with the official Python SDK
(`FastMCP`). Its main job here: let **Claude (claude.ai / Desktop / Code)**
read a folder of documents (e.g. your `brainLNC` knowledge base) through MCP
tools.

It supports two modes:

- **Read-only mode (recommended, used for the claude.ai connector)** — exposes
  only `read_file`, `list_directory`, `search_files`, sandboxed to one folder.
- **Full mode** — also enables `write_file`, `edit_file`, web requests, and
  shell execution. **Only for trusted local use — never expose full mode to a
  network.**

## Setup

A virtualenv at `.venv` (Python 3.13) with `mcp[cli]` + `httpx` is already
created. To recreate elsewhere (including on your future deploy server):

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Quick start: expose your knowledge base to the claude.ai WEB connector

The claude.ai **web** custom connector requires the server to speak OAuth (see
*Why OAuth* below). One command sets up the tunnel + OAuth-enabled server:

```bash
./run_kb_oauth.sh /path/to/brainLNC
```

It prints a block like:

```
 Connector  : https://something.trycloudflare.com/mcp     <-- paste THIS into claude.ai
```

Then in claude.ai → Settings → Connectors → **Add custom connector**:
- **Name:** `brainLNC` (anything)
- **Remote MCP server URL:** the printed `https://….trycloudflare.com/mcp`
  (note the **`/mcp`** suffix)
- Leave the OAuth Client ID/Secret fields empty.
- Click **Add**, then **Connect**. Claude registers, signs in (auto-approved),
  and can then call `list_directory`, `search_files`, and `read_file`.

Keep the terminal running — closing it stops the server and the tunnel.

> ⚠️ **The free `trycloudflare.com` URL is ephemeral** — it changes every time
> you restart, and the tunnel dies when your machine sleeps or the process
> stops. Each restart you must paste the new `…/mcp` URL into claude.ai. For a
> stable URL, see *Deploying* below.

### Why OAuth is required (and the security trade-off)

claude.ai's web connector performs OAuth discovery; if the server has no OAuth,
it fails with *"Couldn't register with the sign-in service"* (Anthropic issue
[claude-ai-mcp#402](https://github.com/anthropics/claude-ai-mcp/issues/402)) —
there is no "auth: none" option in the UI. So `auth_provider.py` implements a
minimal OAuth Authorization Server (Dynamic Client Registration + authorization
code + PKCE) that the SDK wires up automatically when `MCP_PUBLIC_URL` is set.

> 🔐 **Authorization is auto-approved — there is no login/consent screen.** The
> real protection is (1) the unguessable tunnel URL, (2) read-only + sandboxed
> tools. Anyone who learns the URL can complete the flow and read the exposed
> folder. Fine for a personal, ephemeral tunnel; **before a real deployment**,
> add a genuine login/consent step or a pre-shared client secret, and put the
> server on a domain you control.

### Local-only alternative (no OAuth, no tunnel)

If you don't need the **web** app, the **Claude Desktop** app can run this
server locally over stdio with no OAuth and no public exposure — see *Using
locally with Claude Desktop* below. That is the most secure option.

## Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCP_BASE_DIR` | (unset) | Sandbox root. File paths are resolved relative to it and confined inside it. **Set this whenever the server is network-reachable.** |
| `MCP_READ_ONLY` | `0` | `1` = only read tools are registered. |
| `MCP_TRANSPORT` | `stdio` | `stdio` (local clients) or `streamable-http` (remote). |
| `MCP_HOST` | `127.0.0.1` | Bind host for HTTP. |
| `MCP_PORT` | `8000` | Bind port for HTTP. |
| `MCP_PUBLIC_URL` | (unset) | Public HTTPS URL of this server. **When set, OAuth is enabled** (required for the claude.ai web connector). Must match the URL clients actually reach (the tunnel/domain). |
| `MCP_ENABLE_EXEC` | `1` | In full mode only: register `run_command`. |

- `run_kb.sh` → read-only HTTP, no OAuth (for Claude Desktop / local clients).
- `run_kb_oauth.sh` → read-only HTTP **+ tunnel + OAuth** (for claude.ai web).

## Using locally with Claude Desktop / Claude Code (stdio)

No tunnel needed. Add to your client's MCP config:

```json
{
  "mcpServers": {
    "brainLNC": {
      "command": "/Users/trannhatphi/mcpserver/.venv/bin/python",
      "args": ["/Users/trannhatphi/mcpserver/server.py"],
      "env": {
        "MCP_READ_ONLY": "1",
        "MCP_BASE_DIR": "/path/to/brainLNC"
      }
    }
  }
}
```

## Deploying to your own server (later)

The design is portable — only `MCP_BASE_DIR` changes. On your server:

1. Copy this repo, create the venv, put your documents on the server.
2. Run read-only HTTP, pointed at the data path **on that server**:

   ```bash
   MCP_TRANSPORT=streamable-http MCP_READ_ONLY=1 \
   MCP_HOST=0.0.0.0 MCP_PORT=8000 \
   MCP_BASE_DIR=/srv/brainLNC \
   .venv/bin/python server.py
   ```

3. Put it behind HTTPS with a real domain (nginx/Caddy reverse proxy, or a
   named cloudflared tunnel) and use `https://your-domain/mcp` as the connector
   URL. Because the public connector has **no authentication**, keep it
   read-only and sandboxed, and treat the URL as a secret. For real access
   control, add an auth layer (OAuth / reverse-proxy auth) in front.

## Tools

Read-only mode (safe for the remote connector):

| Tool | Description |
| --- | --- |
| `read_file(path)` | Read a text file (path relative to the KB root) |
| `read_lines(path, start, end)` | Read a line range from a large file |
| `read_many_files(paths)` | Read several files in one call |
| `read_pdf(path, max_pages)` | Extract text from a PDF (via pypdf) |
| `read_image(path)` | Return an image (PNG/JPG/…) for Claude to view |
| `list_directory(path)` | List a directory's entries with type and size |
| `directory_tree(path, max_depth)` | Recursive tree of the whole folder in one call |
| `find_files(name_pattern, path)` | Find files by name (substring or glob) |
| `search_files(pattern, path, glob, regex, ignore_case, context)` | Recursive content search; supports regex, case-insensitive, context lines |
| `kb_outline(path)` | Markdown heading outline (TOC) of a file |
| `kb_stats(path)` | KB overview: file counts, sizes, breakdown by folder/type |

Full mode also adds: `write_file`, `edit_file`, `fetch_url`, `http_request`,
and `run_command` (arbitrary shell — local trusted use only).

> After adding/changing tools, **restart the server** and in claude.ai open the
> connector and **Disconnect → Connect** (or remove & re-add) so it re-reads the
> updated tool list.

## Reading from Google Drive (live data source)

So that documents can be **updated on Google Drive and the server picks up the
change automatically** (it reads Drive live on every call — no stale local
copy), the server can read your Drive directly via the Drive API (read-only).

Tools (appear only once authorized): `drive_list`, `drive_search`, `drive_read`
(handles Google Docs, text/Markdown, and PDFs).

### One-time setup

1. **Google Cloud Console** → create/select a project.
2. **APIs & Services → Library** → enable **Google Drive API**.
3. **APIs & Services → OAuth consent screen** → External → add yourself as a
   **Test user** (your Google email).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** →
   application type **Desktop app** → download the JSON, save it as
   `credentials.json` in this folder.
5. Authorize once (opens a browser):

   ```bash
   .venv/bin/python drive_auth.py
   ```

   This writes `token.json` (holds a refresh token). Both files are gitignored.

### Config

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCP_DRIVE_CREDENTIALS` | `credentials.json` | OAuth Desktop client file |
| `MCP_DRIVE_TOKEN` | `token.json` | Saved auth token |
| `MCP_DRIVE_FOLDER` | (unset) | Optional Drive folder name/ID to confine listing to |

Restart the server after `token.json` exists — the three `drive_*` tools then
register automatically. On a headless server (EC2), run `drive_auth.py` on your
laptop and copy `token.json` (and `credentials.json`) up.

## Resources & prompts

- Resource `file://{path}` — file contents (sandboxed, relative to the KB root).
- Prompts `summarize_file(path)` and `code_review(diff)` — example templates.

## Project layout

```
server.py           # entry point — registers tools per mode, wires OAuth, runs transport
run_kb.sh           # launcher: read-only HTTP, sandboxed, no OAuth (local clients)
run_kb_oauth.sh     # launcher: tunnel + read-only HTTP + OAuth (claude.ai web)
auth_provider.py    # minimal in-memory OAuth Authorization Server (DCR + PKCE)
tools/
  file_tools.py     # read/write/edit/list/search + path sandbox (MCP_BASE_DIR)
  web_tools.py      # fetch_url, http_request (httpx, async) — full mode
  exec_tools.py     # run_command (subprocess) — full mode only
resources.py        # file:// resource (sandboxed)
prompts.py          # prompt templates
pyproject.toml      # project metadata + dependencies
```
