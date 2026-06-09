"""MinIO / S3-compatible storage tools for the MCP server.

All local file-tool equivalents (read, list, search, PDF, image, logo, outline,
stats) are provided here so the server can run entirely off MinIO with no local
KB mount required.

Environment variables:
    MCP_S3_ENDPOINT    e.g. http://minio:9000 or https://s3.amazonaws.com
    MCP_S3_ACCESS_KEY
    MCP_S3_SECRET_KEY
    MCP_S3_BUCKET      bucket name (default: brainlnc)
    MCP_S3_REGION      (default: us-east-1)
"""

import io
import os
import re

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

_ENDPOINT = os.environ.get("MCP_S3_ENDPOINT", "http://minio:9000")
_ACCESS_KEY = os.environ.get("MCP_S3_ACCESS_KEY", "admin")
_SECRET_KEY = os.environ.get("MCP_S3_SECRET_KEY", "password123")
_BUCKET = os.environ.get("MCP_S3_BUCKET", "brainlnc")
_REGION = os.environ.get("MCP_S3_REGION", "us-east-1")

_client = None


def _s3():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=_ENDPOINT,
            aws_access_key_id=_ACCESS_KEY,
            aws_secret_access_key=_SECRET_KEY,
            region_name=_REGION,
            config=Config(signature_version="s3v4"),
        )
    return _client


def _get_bytes(key: str) -> bytes:
    obj = _s3().get_object(Bucket=_BUCKET, Key=key)
    return obj["Body"].read()


# ---------------------------------------------------------------------------
# List / browse
# ---------------------------------------------------------------------------

def s3_list(prefix: str = "") -> str:
    """List files and folders in the MinIO bucket under an optional prefix.

    Examples:
        s3_list()                → list everything at bucket root
        s3_list("CHUANCHUNG")   → list files in CHUANCHUNG folder
    """
    try:
        paginator = _s3().get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=_BUCKET, Prefix=prefix, Delimiter="/")

        folders, files = [], []
        for page in pages:
            for cp in page.get("CommonPrefixes") or []:
                folders.append("  dir   " + cp["Prefix"])
            for obj in page.get("Contents") or []:
                size = obj["Size"]
                target = files if not obj["Key"].endswith("/") else folders
                target.append(f"  file  {size:>10,}  {obj['Key']}")

        lines = folders + files
        if not lines:
            loc = f"{_BUCKET}/{prefix}" if prefix else _BUCKET
            return f"(empty: {loc})"
        return f"Bucket: {_BUCKET}/{prefix}\n" + "\n".join(lines)
    except ClientError as e:
        return f"S3 error: {e}"


def s3_directory_tree(prefix: str = "", max_depth: int = 4) -> str:
    """Show the bucket folder structure as a tree (like directory_tree).

    Args:
        prefix:    start path inside the bucket, e.g. "CHUANCHUNG/"
        max_depth: how many levels deep to expand (default 4)
    """
    try:
        paginator = _s3().get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=_BUCKET, Prefix=prefix)

        all_keys = []
        for page in pages:
            for obj in page.get("Contents") or []:
                key = obj["Key"]
                if not key.endswith("/"):
                    all_keys.append(key)

        if not all_keys:
            return f"(empty: {_BUCKET}/{prefix})"

        # Build tree dict
        tree: dict = {}
        for key in sorted(all_keys):
            rel = key[len(prefix):]
            parts = rel.split("/")
            node = tree
            for part in parts:
                node = node.setdefault(part, {})

        lines = [f"{_BUCKET}/{prefix}"]

        def render(node: dict, indent: str, depth: int) -> None:
            if depth > max_depth:
                return
            items = sorted(node.items(), key=lambda kv: (bool(kv[1]), kv[0].lower()))
            for i, (name, children) in enumerate(items):
                last = i == len(items) - 1
                branch = "└── " if last else "├── "
                suffix = "/" if children else ""
                lines.append(indent + branch + name + suffix)
                if children:
                    ext = "    " if last else "│   "
                    render(children, indent + ext, depth + 1)

        render(tree, "", 1)
        return "\n".join(lines)
    except ClientError as e:
        return f"S3 error: {e}"


def s3_find_files(name_pattern: str, prefix: str = "") -> str:
    """Find files by name pattern (substring or glob) in the MinIO bucket.

    Examples: "kpi", "*.pdf", "quy-trinh*"
    """
    import fnmatch
    glob_pat = name_pattern if any(c in name_pattern for c in "*?[") else f"*{name_pattern}*"
    try:
        paginator = _s3().get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=_BUCKET, Prefix=prefix)
        matches = []
        for page in pages:
            for obj in page.get("Contents") or []:
                key = obj["Key"]
                filename = key.split("/")[-1]
                if fnmatch.fnmatch(filename.lower(), glob_pat.lower()):
                    matches.append(key)
        if not matches:
            return f"No files matching {name_pattern!r} in bucket {_BUCKET}/{prefix}"
        return f"Found {len(matches)} file(s):\n" + "\n".join(sorted(matches))
    except ClientError as e:
        return f"S3 error: {e}"


# ---------------------------------------------------------------------------
# Read text
# ---------------------------------------------------------------------------

def s3_read(key: str) -> str:
    """Read a text file from the MinIO bucket by its key (path).

    Example:
        s3_read("CHUANCHUNG/01_Company_Brain.md")
    """
    MAX_CHARS = 500_000
    try:
        body = _get_bytes(key)
        text = body.decode("utf-8", errors="replace")
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + f"\n...[truncated at {MAX_CHARS} chars]"
        return text
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchKey":
            return f"File not found in bucket '{_BUCKET}': {key}"
        return f"S3 error: {e}"


def s3_read_lines(key: str, start: int = 1, end: int = 200) -> str:
    """Read a 1-indexed line range from a text file in MinIO.

    Args:
        key:   file path in bucket, e.g. "CHUANCHUNG/file.md"
        start: first line (1-indexed, inclusive)
        end:   last line (inclusive)
    """
    try:
        body = _get_bytes(key)
        lines_all = body.decode("utf-8", errors="replace").splitlines()
        out = []
        for i, line in enumerate(lines_all, start=1):
            if i < start:
                continue
            if i > end:
                break
            out.append(f"{i}: {line}")
        if not out:
            return f"(no lines in range {start}-{end} for {key})"
        return "\n".join(out)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchKey":
            return f"File not found: {key}"
        return f"S3 error: {e}"


def s3_read_many(keys: list[str]) -> str:
    """Read multiple files from MinIO at once. Returns each file under a header.

    Example:
        s3_read_many(["_INDEX.md", "CHUANCHUNG/file.md"])
    """
    chunks = []
    for key in keys:
        try:
            body = _get_bytes(key)
            content = body.decode("utf-8", errors="replace")
            chunks.append(f"===== {key} =====\n{content}")
        except ClientError as e:
            code = e.response["Error"]["Code"]
            err = "not found" if code == "NoSuchKey" else str(e)
            chunks.append(f"===== {key} =====\n[error: {err}]")
    return "\n\n".join(chunks) if chunks else "(no files requested)"


def s3_kb_outline(key: str) -> str:
    """Extract the Markdown heading outline (table of contents) from a file in MinIO.

    Lists every # heading with its level and line number so you can jump to a
    section with s3_read_lines. Headings inside fenced code blocks are ignored.
    """
    try:
        body = _get_bytes(key)
        lines_all = body.decode("utf-8", errors="replace").splitlines()
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchKey":
            return f"File not found: {key}"
        return f"S3 error: {e}"

    out = []
    in_code = False
    for lineno, line in enumerate(lines_all, start=1):
        s = line.strip()
        if s.startswith("```") or s.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code or not s.startswith("#"):
            continue
        hashes = len(s) - len(s.lstrip("#"))
        if 1 <= hashes <= 6 and s[hashes:hashes + 1] in (" ", ""):
            title = s[hashes:].strip()
            out.append(f"{'  ' * (hashes - 1)}- L{hashes} (line {lineno}): {title}")
    if not out:
        return f"(no Markdown headings found in {key})"
    return f"Outline of {key} ({len(out)} headings):\n" + "\n".join(out)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def s3_search(pattern: str, prefix: str = "") -> str:
    """Search for text across all files in the MinIO bucket.

    Args:
        pattern: substring to search for (case-insensitive)
        prefix:  optional folder prefix to limit the search
    """
    MAX_RESULTS = 50
    needle = pattern.lower()
    results = []

    try:
        paginator = _s3().get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=_BUCKET, Prefix=prefix)

        for page in pages:
            for obj in page.get("Contents") or []:
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                ext = os.path.splitext(key)[1].lower()
                if ext not in {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html"}:
                    continue
                try:
                    body = _s3().get_object(Bucket=_BUCKET, Key=key)["Body"].read()
                    text = body.decode("utf-8", errors="ignore")
                    for i, line in enumerate(text.splitlines(), 1):
                        if needle in line.lower():
                            results.append(f"{key}:{i}: {line.strip()}")
                            if len(results) >= MAX_RESULTS:
                                break
                except ClientError:
                    continue
                if len(results) >= MAX_RESULTS:
                    break
            if len(results) >= MAX_RESULTS:
                break

    except ClientError as e:
        return f"S3 error: {e}"

    if not results:
        return f"No matches for '{pattern}' in bucket {_BUCKET}/{prefix}"
    suffix = " (truncated)" if len(results) >= MAX_RESULTS else ""
    return f"Found {len(results)} match(es){suffix}:\n" + "\n".join(results)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def s3_kb_stats() -> str:
    """Overview stats of the MinIO bucket: file counts, sizes, by folder and extension."""
    try:
        paginator = _s3().get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=_BUCKET)

        total_files = 0
        total_bytes = 0
        by_ext: dict[str, int] = {}
        by_top: dict[str, list] = {}

        for page in pages:
            for obj in page.get("Contents") or []:
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                size = obj["Size"]
                total_files += 1
                total_bytes += size
                ext = os.path.splitext(key)[1].lower() or "(no ext)"
                by_ext[ext] = by_ext.get(ext, 0) + 1
                top = key.split("/")[0] if "/" in key else "."
                stats = by_top.setdefault(top, [0, 0])
                stats[0] += 1
                stats[1] += size

        def human(n: int) -> str:
            size = float(n)
            for unit in ("B", "KB", "MB", "GB"):
                if size < 1024 or unit == "GB":
                    return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
                size /= 1024
            return f"{size:.1f}GB"

        lines = [
            f"Bucket: {_BUCKET}",
            f"Total: {total_files} files, {human(total_bytes)}",
            "",
            "By extension:",
        ]
        for ext, cnt in sorted(by_ext.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {ext:12} {cnt}")
        lines.append("")
        lines.append("By top-level folder:")
        for top, (cnt, size) in sorted(by_top.items()):
            lines.append(f"  {top:28} {cnt:4} files  {human(size)}")
        return "\n".join(lines)
    except ClientError as e:
        return f"S3 error: {e}"


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def s3_read_pdf(key: str, max_pages: int = 30) -> str:
    """Extract text from a PDF stored in MinIO.

    Args:
        key:       file path in bucket, e.g. "HO-SO-NANG-LUC/profile.pdf"
        max_pages: maximum number of pages to extract (default 30)
    """
    try:
        body = _get_bytes(key)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchKey":
            return f"File not found: {key}"
        return f"S3 error: {e}"

    try:
        from pypdf import PdfReader
    except ImportError:
        return "pypdf not installed — cannot extract PDF text."

    MAX_CHARS = 50_000
    reader = PdfReader(io.BytesIO(body))
    total = len(reader.pages)
    out = [f"PDF: {key} ({total} page(s), showing up to {max_pages})"]
    chars = 0
    for i, page in enumerate(reader.pages[:max_pages], start=1):
        text = (page.extract_text() or "").strip()
        out.append(f"\n--- page {i} ---\n{text}")
        chars += len(text)
        if chars >= MAX_CHARS:
            out.append(f"\n...[truncated at {MAX_CHARS} characters]")
            break
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Images & logos
# ---------------------------------------------------------------------------

_SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def s3_list_logos(path: str = "logo") -> str:
    """List all logo images in the MinIO bucket under the logo/ folder.

    Use the key with s3_get_logo() to retrieve or resize a logo.
    """
    prefix = path.rstrip("/") + "/"
    try:
        paginator = _s3().get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=_BUCKET, Prefix=prefix)

        try:
            from PIL import Image as PILImage
            has_pil = True
        except ImportError:
            has_pil = False

        rows = []
        for page in pages:
            for obj in page.get("Contents") or []:
                key = obj["Key"]
                ext = os.path.splitext(key)[1].lower()
                if ext not in _SUPPORTED_EXTS:
                    continue
                size_bytes = obj["Size"]
                dims = ""
                if has_pil:
                    try:
                        data = _get_bytes(key)
                        with PILImage.open(io.BytesIO(data)) as img:
                            dims = f"  {img.width}x{img.height}px"
                    except Exception:
                        pass
                rows.append(f"  {key}{dims}  ({size_bytes:,} bytes)")

        if not rows:
            return f"No logos found in bucket under {prefix}"
        return f"Available logos ({len(rows)}):\n" + "\n".join(rows)
    except ClientError as e:
        return f"S3 error: {e}"


def s3_get_logo(key: str, width: int = 0, height: int = 0):
    """Return a logo image from MinIO, optionally resized.

    Args:
        key:    Full key in bucket, e.g. "logo/lnc_logo.png". Use s3_list_logos() to see options.
        width:  Target width in pixels. 0 = derive from height (keeps aspect ratio).
        height: Target height in pixels. 0 = derive from width (keeps aspect ratio).

    If both width and height are 0, the original image is returned unchanged.
    """
    from mcp.server.fastmcp import Image

    ext = os.path.splitext(key)[1].lower()
    if ext not in _SUPPORTED_EXTS:
        raise ValueError(f"Unsupported image type {ext!r} — supported: {sorted(_SUPPORTED_EXTS)}")

    try:
        body = _get_bytes(key)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchKey":
            raise FileNotFoundError(f"Logo not found in bucket: {key}")
        raise RuntimeError(f"S3 error: {e}")

    if width == 0 and height == 0:
        mime = "image/jpeg" if ext in {".jpg", ".jpeg"} else "image/png"
        return Image(data=body, format=mime)

    try:
        from PIL import Image as PILImage
    except ImportError:
        raise RuntimeError("Pillow is not installed — cannot resize images.")

    with PILImage.open(io.BytesIO(body)) as img:
        orig_w, orig_h = img.size
        if width > 0 and height == 0:
            height = max(1, round(orig_h * width / orig_w))
        elif height > 0 and width == 0:
            width = max(1, round(orig_w * height / orig_h))

        resized = img.resize((width, height), PILImage.LANCZOS)
        buf = io.BytesIO()
        out_fmt = "JPEG" if ext in {".jpg", ".jpeg"} else "PNG"
        save_kwargs = {"format": out_fmt}
        if out_fmt == "JPEG":
            save_kwargs["quality"] = 90
            if resized.mode in ("RGBA", "P"):
                resized = resized.convert("RGB")
        resized.save(buf, **save_kwargs)

    mime = "image/jpeg" if out_fmt == "JPEG" else "image/png"
    return Image(data=buf.getvalue(), format=mime)
