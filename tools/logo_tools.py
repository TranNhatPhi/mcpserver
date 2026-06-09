"""Logo tools: list and serve brand logos at specific sizes.

Logos live under a subfolder (default: "logo/") inside the KB root.
The get_logo tool resizes with Pillow (LANCZOS) while preserving aspect ratio
when only one dimension is specified.
"""

import io
import os

from mcp.server.fastmcp import Image

from tools.file_tools import BASE_DIR, _display, _resolve

LOGO_DIR = "logo"
_SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def list_logos(path: str = LOGO_DIR) -> str:
    """List all available logos in the logo directory.

    Returns filename, pixel dimensions, and file size for each logo.
    Use the filename with get_logo() to retrieve or resize a logo.
    """
    abs_path = _resolve(path)
    if not os.path.isdir(abs_path):
        raise NotADirectoryError(f"Logo directory not found: {_display(abs_path)}")

    try:
        from PIL import Image as PILImage
        has_pil = True
    except ImportError:
        has_pil = False

    rows = []
    for name in sorted(os.listdir(abs_path)):
        ext = os.path.splitext(name)[1].lower()
        if ext not in _SUPPORTED_EXTS:
            continue
        fp = os.path.join(abs_path, name)
        size_bytes = os.path.getsize(fp)
        dims = ""
        if has_pil:
            try:
                with PILImage.open(fp) as img:
                    dims = f"  {img.width}x{img.height}px"
            except Exception:
                pass
        rows.append(f"  {name}{dims}  ({size_bytes:,} bytes)")

    if not rows:
        return f"No logos found in {_display(abs_path)}"
    return f"Available logos ({len(rows)}):\n" + "\n".join(rows)


def get_logo(
    name: str,
    width: int = 0,
    height: int = 0,
    path: str = LOGO_DIR,
) -> Image:
    """Return a logo image, optionally resized to the requested dimensions.

    Args:
        name:   Logo filename, e.g. "lc_logo_master.jpg.jpeg". Use list_logos()
                to see what's available.
        width:  Target width in pixels. 0 = derive from height (keeps aspect ratio).
        height: Target height in pixels. 0 = derive from width (keeps aspect ratio).
        path:   Subdirectory containing logos (default: "logo").

    If both width and height are 0, the original image is returned unchanged.
    If only one dimension is given, the other is scaled proportionally.
    If both are given, the image is stretched to exactly that size.
    """
    abs_dir = _resolve(path)
    abs_path = os.path.realpath(os.path.join(abs_dir, name))

    # Sandbox check — prevent escaping BASE_DIR via the name argument
    if BASE_DIR and not (abs_path == BASE_DIR or abs_path.startswith(BASE_DIR + os.sep)):
        raise PermissionError(f"Path outside sandbox: {name!r}")

    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Logo not found: {name!r} in {_display(abs_dir)}")

    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in _SUPPORTED_EXTS:
        raise ValueError(f"Unsupported image type {ext!r} — supported: {sorted(_SUPPORTED_EXTS)}")

    # No resize requested → return original bytes directly
    if width == 0 and height == 0:
        return Image(path=abs_path)

    try:
        from PIL import Image as PILImage
    except ImportError:
        raise RuntimeError(
            "Pillow is not installed. Add 'pillow' to pyproject.toml and rebuild."
        )

    with PILImage.open(abs_path) as img:
        orig_w, orig_h = img.size

        # Compute missing dimension to preserve aspect ratio
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
            # JPEG can't have alpha channel
            if resized.mode in ("RGBA", "P"):
                resized = resized.convert("RGB")
        resized.save(buf, **save_kwargs)

    mime = "image/jpeg" if out_fmt == "JPEG" else "image/png"
    return Image(data=buf.getvalue(), format=mime)
