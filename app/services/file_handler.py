"""Service layer: STL file validation and safe persistence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

# How many bytes we read at once while streaming to disk
_CHUNK_SIZE: int = 1024 * 256  # 256 KB


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SavedFile:
    original_filename: str
    saved_path: Path
    size_bytes: int


# ---------------------------------------------------------------------------
# Custom exceptions (caught in the route layer)
# ---------------------------------------------------------------------------


class InvalidFileTypeError(ValueError):
    """Raised when the uploaded file is not an allowed type."""


class FileTooLargeError(ValueError):
    """Raised when the uploaded file exceeds the size limit."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _assert_extension(filename: str) -> None:
    """Raise InvalidFileTypeError if the extension is not in the allow-list."""
    ext = Path(filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        allowed = ", ".join(sorted(settings.allowed_extensions))
        raise InvalidFileTypeError(
            f"Extension '{ext}' is not allowed. Accepted: {allowed}"
        )


def _safe_filename(original: str) -> str:
    """Return a collision-safe filename: <uuid4>_<sanitised-original>."""
    stem = Path(original).stem
    ext = Path(original).suffix.lower()

    # Strip characters that are problematic on any OS
    safe_stem = "".join(c if (c.isalnum() or c in "-_") else "_" for c in stem)
    safe_stem = safe_stem[:64]  # cap length

    return f"{uuid.uuid4().hex}_{safe_stem}{ext}"


def _ensure_upload_dir() -> Path:
    """Create the upload directory if it does not exist and return its Path."""
    upload_dir: Path = settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def validate_and_save(upload: UploadFile) -> SavedFile:
    """
    Validate an uploaded file and stream it safely to disk.

    Raises:
        InvalidFileTypeError: extension is not .stl
        FileTooLargeError:    content exceeds settings.max_upload_size_bytes
    """
    original_filename: str = upload.filename or "unknown"

    # 1. Extension check (fast — no I/O needed)
    _assert_extension(original_filename)

    # 2. Stream to disk while counting bytes; reject mid-stream if too large
    upload_dir = _ensure_upload_dir()
    dest_filename = _safe_filename(original_filename)
    dest_path = upload_dir / dest_filename

    total_bytes = 0

    try:
        with dest_path.open("wb") as fh:
            while True:
                chunk: bytes = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break

                total_bytes += len(chunk)

                if total_bytes > settings.max_upload_size_bytes:
                    # Clean up the partial file before raising
                    fh.close()
                    dest_path.unlink(missing_ok=True)
                    raise FileTooLargeError(
                        f"File exceeds the {settings.max_upload_size_bytes // (1024 * 1024)} MB limit."
                    )

                fh.write(chunk)
    except (InvalidFileTypeError, FileTooLargeError):
        raise
    except Exception as exc:
        # Unexpected I/O error — clean up and re-raise
        dest_path.unlink(missing_ok=True)
        logger.error("Unexpected error saving upload '%s': %s", original_filename, exc, exc_info=True)
        raise

    logger.info(
        "Saved upload | original='%s' dest='%s' size=%d bytes",
        original_filename,
        dest_path,
        total_bytes,
    )

    return SavedFile(
        original_filename=original_filename,
        saved_path=dest_path,
        size_bytes=total_bytes,
    )
