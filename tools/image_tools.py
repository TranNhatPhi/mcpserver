"""Image reading tool — returns image content for Claude to view. Sandboxed."""

import os

from mcp.server.fastmcp import Image

from tools.file_tools import _display, _resolve

MAX_IMAGE_BYTES = 5_000_000
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def read_image(path: str) -> Image:
    """Return an image file (PNG/JPG/GIF/WEBP/BMP) so Claude can view it.

    The path is relative to the knowledge-base root. Use this for the screenshots
    and logo under the knowledge base (e.g. kichban/image/...).
    """
    abs_path = _resolve(path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Not a file: {_display(abs_path)}")
    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in IMAGE_EXTS:
        raise ValueError(f"Not a supported image ({', '.join(sorted(IMAGE_EXTS))}): {_display(abs_path)}")
    size = os.path.getsize(abs_path)
    if size > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image too large ({size} bytes > {MAX_IMAGE_BYTES} limit): {_display(abs_path)}"
        )
    return Image(path=abs_path)
