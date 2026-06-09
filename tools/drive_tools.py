"""Google Drive read tools for the MCP server.

The server reads the user's Google Drive directly via the Drive API (read-only).
Auth is OAuth user-flow with a persisted token:

  credentials.json  - OAuth *Desktop app* client downloaded from Google Cloud
  token.json        - created once by `drive_auth.py` (holds the refresh token)

Optionally scope everything to one folder by setting MCP_DRIVE_FOLDER to the
folder's name or ID.

Paths to these files come from env (defaults are project-root relative):
  MCP_DRIVE_CREDENTIALS (default credentials.json)
  MCP_DRIVE_TOKEN       (default token.json)
  MCP_DRIVE_FOLDER      (optional folder name or ID to confine to)
"""

import io
import os
import threading

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
MAX_TEXT_CHARS = 50_000

CREDENTIALS_PATH = os.environ.get("MCP_DRIVE_CREDENTIALS", "credentials.json")
TOKEN_PATH = os.environ.get("MCP_DRIVE_TOKEN", "token.json")
DRIVE_FOLDER = os.environ.get("MCP_DRIVE_FOLDER", "").strip()

_service = None  # lazily-built Drive API client
_root_folder_id = None  # resolved once if DRIVE_FOLDER is set
_service_lock = threading.Lock()  # prevents concurrent init race in thread pool


def is_configured() -> bool:
    """True if a saved token exists (so Drive tools can be registered)."""
    return os.path.isfile(TOKEN_PATH)


def _get_service():
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is not None:  # double-checked locking
            return _service
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not os.path.isfile(TOKEN_PATH):
            raise RuntimeError(
                f"Drive not authorized: {TOKEN_PATH} missing. "
                "Run `.venv/bin/python drive_auth.py` first."
            )
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(TOKEN_PATH, "w") as f:
                    f.write(creds.to_json())
            else:
                raise RuntimeError("Drive token invalid; re-run drive_auth.py")
        _service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _service


def _resolve_folder_id(name_or_id: str) -> str | None:
    """Resolve a folder given its name or ID; return the folder ID or None."""
    svc = _get_service()
    # Treat as an ID first (IDs have no spaces and are ~30+ chars).
    if " " not in name_or_id and len(name_or_id) > 20:
        try:
            meta = svc.files().get(fileId=name_or_id, fields="id,mimeType").execute()
            if meta.get("mimeType") == "application/vnd.google-apps.folder":
                return meta["id"]
        except Exception:  # noqa: BLE001
            pass
    safe = name_or_id.replace("'", "\\'")
    q = (
        "mimeType='application/vnd.google-apps.folder' and trashed=false "
        f"and name='{safe}'"
    )
    res = svc.files().list(q=q, fields="files(id,name)", pageSize=1).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _confine_folder_id() -> str | None:
    global _root_folder_id
    if not DRIVE_FOLDER:
        return None
    if _root_folder_id is None:
        _root_folder_id = _resolve_folder_id(DRIVE_FOLDER)
        if _root_folder_id is None:
            raise RuntimeError(f"MCP_DRIVE_FOLDER {DRIVE_FOLDER!r} not found on Drive")
    return _root_folder_id


def _fmt(files: list[dict]) -> str:
    lines = []
    for f in files:
        kind = "dir " if f.get("mimeType") == "application/vnd.google-apps.folder" else "file"
        size = f.get("size", "-")
        lines.append(f"{kind}  {size:>9}  {f['name']}   [id:{f['id']}]")
    return "\n".join(lines)


def drive_list(folder: str = "", max_results: int = 100) -> str:
    """List files/folders in Google Drive.

    `folder` is an optional folder name or ID to list inside; empty lists the
    configured root folder (MCP_DRIVE_FOLDER) or the Drive root. Each entry shows
    its name and Drive id (use the id with drive_read).
    """
    svc = _get_service()
    if folder:
        parent = _resolve_folder_id(folder)
        if parent is None:
            return f"Folder not found: {folder!r}"
    else:
        parent = _confine_folder_id()  # may be None -> root listing

    q = "trashed=false"
    if parent:
        q += f" and '{parent}' in parents"
    res = (
        svc.files()
        .list(
            q=q,
            fields="files(id,name,mimeType,size)",
            pageSize=min(max_results, 1000),
            orderBy="folder,name",
        )
        .execute()
    )
    files = res.get("files", [])
    if not files:
        return f"(no files in {folder or DRIVE_FOLDER or 'Drive root'})"
    return f"{len(files)} item(s):\n" + _fmt(files)


def drive_search(query: str, max_results: int = 50) -> str:
    """Full-text search across Google Drive file names and contents.

    Returns matching files with their name and Drive id.
    """
    svc = _get_service()
    safe = query.replace("'", "\\'")
    q = f"trashed=false and (name contains '{safe}' or fullText contains '{safe}')"
    res = (
        svc.files()
        .list(q=q, fields="files(id,name,mimeType,size)", pageSize=min(max_results, 1000))
        .execute()
    )
    files = res.get("files", [])
    if not files:
        return f"No Drive files matching {query!r}"
    return f"Found {len(files)} file(s):\n" + _fmt(files)


def drive_read(file: str, max_pages: int = 30) -> str:
    """Read a Google Drive file's text content by its name or Drive id.

    Handles Google Docs (exported as text), plain text/Markdown, and PDFs
    (text extracted via pypdf). If a name matches several files, the first is
    used.
    """
    svc = _get_service()
    file_id = file
    name = file
    mime = None
    # If it doesn't look like an ID, resolve by name.
    if " " in file or len(file) <= 20:
        safe = file.replace("'", "\\'")
        res = (
            svc.files()
            .list(q=f"trashed=false and name='{safe}'", fields="files(id,name,mimeType)", pageSize=1)
            .execute()
        )
        hits = res.get("files", [])
        if not hits:
            return f"File not found: {file!r}"
        file_id, name, mime = hits[0]["id"], hits[0]["name"], hits[0]["mimeType"]
    if mime is None:
        meta = svc.files().get(fileId=file_id, fields="id,name,mimeType").execute()
        name, mime = meta["name"], meta["mimeType"]

    # Google-native docs: export to text.
    if mime.startswith("application/vnd.google-apps"):
        if mime == "application/vnd.google-apps.folder":
            return f"{name!r} is a folder, not a readable file."
        data = svc.files().export(fileId=file_id, mimeType="text/plain").execute()
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
        return _truncate(f"# {name}\n\n{text}")

    # Binary/file: download bytes.
    from googleapiclient.http import MediaIoBaseDownload

    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    raw = buf.getvalue()

    if mime == "application/pdf" or name.lower().endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        out = [f"PDF: {name} ({len(reader.pages)} pages)"]
        for i, page in enumerate(reader.pages[:max_pages], start=1):
            out.append(f"\n--- page {i} ---\n{(page.extract_text() or '').strip()}")
        return _truncate("\n".join(out))

    # Assume text.
    return _truncate(f"# {name}\n\n{raw.decode('utf-8', 'replace')}")


def _truncate(text: str) -> str:
    if len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS] + f"\n...[truncated at {MAX_TEXT_CHARS} chars]"
    return text
