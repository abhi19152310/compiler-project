"""Validate image URLs and safe, relative local asset paths."""

from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def is_supported_image(data: bytes, extension: str) -> bool:
    signatures = {
        ".png": lambda value: value.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": lambda value: value.startswith(b"\xff\xd8\xff"),
        ".jpeg": lambda value: value.startswith(b"\xff\xd8\xff"),
        ".gif": lambda value: value.startswith((b"GIF87a", b"GIF89a")),
        ".webp": lambda value: len(value) >= 12 and value[:4] == b"RIFF" and value[8:12] == b"WEBP",
    }
    return extension.lower() in signatures and signatures[extension.lower()](data)


def local_asset_path(source: str) -> PurePosixPath | None:
    if not source or any(ord(character) < 32 for character in source):
        raise ValueError("Image source is empty or contains control characters.")
    try:
        parsed = urlsplit(source)
    except ValueError as error:
        raise ValueError("Image source is not a valid URL.") from error
    if parsed.scheme in {"http", "https"}:
        if not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in source) or "\\" in source:
            raise ValueError("Image URLs must use HTTP(S) and cannot contain credentials.")
        if parsed.port == 0:
            raise ValueError("Image URL port cannot be zero.")
        return None
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Local image sources must be relative file paths.")
    path = unquote(parsed.path)
    parts = path.split("/")
    if (
        not path or path.startswith("/") or "\\" in path
        or any(part in {"", ".", ".."} for part in parts)
        or any(ord(character) < 32 for character in path)
        or PurePosixPath(path).suffix.lower() not in IMAGE_EXTENSIONS
    ):
        raise ValueError("Local image sources must be safe PNG, JPEG, GIF, or WebP file paths.")
    return PurePosixPath(*parts)
