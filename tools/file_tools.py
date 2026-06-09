"""File system tools: read, write, edit, list, search.

Path sandboxing
---------------
If the MCP_BASE_DIR environment variable is set, every path argument is
resolved *relative to that base directory* and is confined within it: any
attempt to escape the base (via ``..`` or an absolute path) raises an error.
This lets the server safely expose a single knowledge-base folder without
giving access to the rest of the filesystem.

If MCP_BASE_DIR is not set, paths are resolved against the current working
directory with no confinement (full-filesystem mode — only for trusted local
use).
"""

import fnmatch
import functools
import os
import re

MAX_READ_BYTES = 1_000_000

# Realpath of the sandbox root, or None for unconfined mode.
_base = os.environ.get("MCP_BASE_DIR")
BASE_DIR = os.path.realpath(os.path.expanduser(_base)) if _base else None


def _resolve(path: str) -> str:
    """Resolve a user-supplied path, confining it to BASE_DIR when set.

    Within a sandbox, incoming paths are treated as relative to the base dir
    (leading slashes are stripped), then fully resolved and checked to ensure
    they stay inside the base — blocking ``..`` traversal and symlink escapes.
    """
    if BASE_DIR is None:
        return os.path.abspath(os.path.expanduser(path))

    rel = os.path.expanduser(path).lstrip("/\\")
    candidate = os.path.realpath(os.path.join(BASE_DIR, rel))
    if candidate != BASE_DIR and not candidate.startswith(BASE_DIR + os.sep):
        raise PermissionError(
            f"Path {path!r} is outside the allowed base directory"
        )
    return candidate


def _display(abs_path: str) -> str:
    """Show paths relative to the sandbox root (hide host absolute paths)."""
    if BASE_DIR is None:
        return abs_path
    rel = os.path.relpath(abs_path, BASE_DIR)
    return "." if rel == "." else rel


@functools.lru_cache(maxsize=256)
def _read_file_cached(abs_path: str, mtime_ns: int, size: int) -> str:
    """Inner cached read — keyed on path + mtime + size so stale content is never returned."""
    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def read_file(path: str) -> str:
    """Read and return the text content of a file.

    The path is relative to the knowledge-base root that this server exposes.
    Results are cached in memory; the cache is invalidated automatically when
    the file's modification time or size changes.
    """
    abs_path = _resolve(path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Not a file: {_display(abs_path)}")
    st = os.stat(abs_path)
    if st.st_size > MAX_READ_BYTES:
        raise ValueError(
            f"File too large ({st.st_size} bytes > {MAX_READ_BYTES} byte limit): "
            f"{_display(abs_path)}"
        )
    return _read_file_cached(abs_path, st.st_mtime_ns, st.st_size)


def write_file(path: str, content: str) -> str:
    """Create or overwrite a file with the given text content.

    The path is relative to the knowledge-base root that this server exposes.
    """
    abs_path = _resolve(path)
    parent = os.path.dirname(abs_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote {len(content.encode('utf-8'))} bytes to {_display(abs_path)}"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace the first occurrence of old_text with new_text in a file.

    Errors if old_text is not found, or appears more than once (to avoid
    ambiguous edits) — provide more surrounding context to make it unique.
    The path is relative to the knowledge-base root that this server exposes.
    """
    abs_path = _resolve(path)
    content = read_file(path)
    count = content.count(old_text)
    if count == 0:
        raise ValueError(f"old_text not found in {_display(abs_path)}")
    if count > 1:
        raise ValueError(
            f"old_text appears {count} times in {_display(abs_path)}; "
            "provide more context to make it unique"
        )
    new_content = content.replace(old_text, new_text, 1)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return f"Edited {_display(abs_path)} (replaced 1 occurrence)"


def list_directory(path: str = ".") -> str:
    """List entries in a directory with their type (file/dir) and size in bytes.

    The path is relative to the knowledge-base root that this server exposes;
    use "." for the root.
    """
    abs_path = _resolve(path)
    if not os.path.isdir(abs_path):
        raise NotADirectoryError(f"Not a directory: {_display(abs_path)}")
    lines = []
    for entry in sorted(os.scandir(abs_path), key=lambda e: e.name):
        kind = "dir" if entry.is_dir() else "file"
        size = entry.stat().st_size if entry.is_file() else "-"
        lines.append(f"{kind:4}  {size:>10}  {entry.name}")
    header = _display(abs_path)
    if not lines:
        return f"(empty directory: {header})"
    return f"{header}:\n" + "\n".join(lines)


def search_files(
    pattern: str,
    path: str = ".",
    glob: str = "*",
    regex: bool = False,
    ignore_case: bool = False,
    context: int = 0,
) -> str:
    """Recursively search for text in files under path matching glob (grep -rn).

    Args:
        pattern: text (substring) or a regular expression if regex=True.
        path: directory to search, relative to the knowledge-base root.
        glob: filename filter, e.g. "*.md".
        regex: treat pattern as a Python regular expression.
        ignore_case: case-insensitive matching.
        context: number of lines to show before/after each match.

    Returns matching file paths (relative to the KB root) with line numbers.
    """
    abs_path = _resolve(path)
    if not os.path.isdir(abs_path):
        raise NotADirectoryError(f"Not a directory: {_display(abs_path)}")

    flags = re.IGNORECASE if ignore_case else 0
    if regex:
        matcher = re.compile(pattern, flags)
        def is_match(line: str) -> bool:
            return matcher.search(line) is not None
    elif ignore_case:
        needle = pattern.lower()
        def is_match(line: str) -> bool:
            return needle in line.lower()
    else:
        def is_match(line: str) -> bool:
            return pattern in line

    results = []
    max_results = 200
    for root, _dirs, files in os.walk(abs_path):
        for name in sorted(files):
            if not fnmatch.fnmatch(name, glob):
                continue
            file_path = os.path.join(root, name)
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except OSError:
                continue
            for i, line in enumerate(lines):
                if not is_match(line):
                    continue
                rel = _display(file_path)
                if context > 0:
                    lo, hi = max(0, i - context), min(len(lines), i + context + 1)
                    block = [
                        f"{rel}:{j + 1}:{'>' if j == i else ' '} {lines[j].rstrip()}"
                        for j in range(lo, hi)
                    ]
                    results.append("\n".join(block))
                else:
                    results.append(f"{rel}:{i + 1}: {line.rstrip()}")
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    if not results:
        return f"No matches for {pattern!r} under {_display(abs_path)} (glob={glob})"
    suffix = " (truncated)" if len(results) >= max_results else ""
    sep = "\n--\n" if context > 0 else "\n"
    return f"Found {len(results)} match(es){suffix}:\n" + sep.join(results)


def directory_tree(path: str = ".", max_depth: int = 4) -> str:
    """Return a recursive tree view of a directory (relative to the KB root).

    Shows the whole folder structure in one call, up to max_depth levels.
    """
    abs_path = _resolve(path)
    if not os.path.isdir(abs_path):
        raise NotADirectoryError(f"Not a directory: {_display(abs_path)}")

    lines = [_display(abs_path) + "/"]
    count = {"n": 0}
    cap = 2000

    def walk(d: str, prefix: str, depth: int) -> None:
        if depth > max_depth or count["n"] >= cap:
            return
        try:
            entries = sorted(
                os.scandir(d), key=lambda e: (not e.is_dir(), e.name.lower())
            )
        except OSError:
            return
        for i, entry in enumerate(entries):
            if count["n"] >= cap:
                lines.append(prefix + "└── … (truncated)")
                return
            last = i == len(entries) - 1
            branch = "└── " if last else "├── "
            name = entry.name + ("/" if entry.is_dir() else "")
            lines.append(prefix + branch + name)
            count["n"] += 1
            if entry.is_dir():
                walk(entry.path, prefix + ("    " if last else "│   "), depth + 1)

    walk(abs_path, "", 1)
    return "\n".join(lines)


def find_files(name_pattern: str, path: str = ".") -> str:
    """Find files by name (substring or glob) recursively under path.

    Examples: "kpi", "*.pdf", "quy-trinh*". Returns matching relative paths.
    """
    abs_path = _resolve(path)
    if not os.path.isdir(abs_path):
        raise NotADirectoryError(f"Not a directory: {_display(abs_path)}")

    glob_pat = name_pattern if any(c in name_pattern for c in "*?[") else f"*{name_pattern}*"
    matches = []
    for root, _dirs, files in os.walk(abs_path):
        for name in sorted(files):
            if fnmatch.fnmatch(name.lower(), glob_pat.lower()):
                matches.append(_display(os.path.join(root, name)))
    if not matches:
        return f"No files matching {name_pattern!r} under {_display(abs_path)}"
    return f"Found {len(matches)} file(s):\n" + "\n".join(sorted(matches))


def read_lines(path: str, start: int = 1, end: int = 200) -> str:
    """Read a 1-indexed inclusive line range from a (possibly large) text file."""
    abs_path = _resolve(path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Not a file: {_display(abs_path)}")
    out = []
    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, start=1):
            if lineno < start:
                continue
            if lineno > end:
                break
            out.append(f"{lineno}: {line.rstrip()}")
    if not out:
        return f"(no lines in range {start}-{end} for {_display(abs_path)})"
    return "\n".join(out)


def read_many_files(paths: list[str]) -> str:
    """Read several files at once. Returns each file's content under a header."""
    chunks = []
    for p in paths:
        try:
            content = read_file(p)
            chunks.append(f"===== {p} =====\n{content}")
        except Exception as e:  # noqa: BLE001 - report per-file errors inline
            chunks.append(f"===== {p} =====\n[error: {type(e).__name__}: {e}]")
    return "\n\n".join(chunks) if chunks else "(no files requested)"


def kb_outline(path: str) -> str:
    """Extract the Markdown heading outline (table of contents) of a file.

    Lists every `#`..`######` heading with its level and line number, so you can
    jump straight to a section with read_lines. The path is relative to the KB
    root. Headings inside fenced code blocks are ignored.
    """
    abs_path = _resolve(path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Not a file: {_display(abs_path)}")
    out = []
    in_code = False
    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, start=1):
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
        return f"(no Markdown headings found in {_display(abs_path)})"
    return f"Outline of {_display(abs_path)} ({len(out)} headings):\n" + "\n".join(out)


def kb_stats(path: str = ".") -> str:
    """Overview stats of the knowledge base: file counts, sizes, breakdowns.

    Counts files by extension and by top-level subfolder under path (relative to
    the KB root) — a quick map of how much content exists and where.
    """
    abs_path = _resolve(path)
    if not os.path.isdir(abs_path):
        raise NotADirectoryError(f"Not a directory: {_display(abs_path)}")

    total_files = 0
    total_bytes = 0
    by_ext: dict[str, int] = {}
    by_top: dict[str, list[int]] = {}
    for root, _dirs, files in os.walk(abs_path):
        rel_root = os.path.relpath(root, abs_path)
        top = "." if rel_root == "." else rel_root.split(os.sep)[0]
        for name in files:
            fp = os.path.join(root, name)
            try:
                size = os.path.getsize(fp)
            except OSError:
                continue
            total_files += 1
            total_bytes += size
            ext = os.path.splitext(name)[1].lower() or "(no ext)"
            by_ext[ext] = by_ext.get(ext, 0) + 1
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
        f"Knowledge base: {_display(abs_path)}",
        f"Total: {total_files} files, {human(total_bytes)}",
        "",
        "By extension:",
    ]
    for ext, cnt in sorted(by_ext.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {ext:10} {cnt}")
    lines.append("")
    lines.append("By top-level folder:")
    for top, (cnt, size) in sorted(by_top.items()):
        lines.append(f"  {top:24} {cnt:4} files  {human(size)}")
    return "\n".join(lines)
