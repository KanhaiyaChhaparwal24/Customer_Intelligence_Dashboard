"""
local_file_service.py
Helpers to read local invoice files (images/PDF) into memory for OCR.
"""
import io
import mimetypes
from pathlib import Path
from typing import Tuple

from config import LOCAL_SHEETS_DIR


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    # Fallback for common types
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".pdf":
        return "application/pdf"
    return "application/octet-stream"


def stream_local_file_to_memory(folder: str, filename: str) -> Tuple[bytes, str, str]:
    """Open a file from `folder` and return (bytes, mime_type, actual_name).
    Raises ValueError if not found or size is 0.
    """
    base = Path(folder)
    repo_root = base.parent
    search_dirs = [base, repo_root / "downloads", repo_root]

    candidate = None
    for directory in search_dirs:
        if not directory.exists():
            continue

        exact = directory / filename
        if exact.exists():
            candidate = exact
            break

        normalized_target = "".join(ch.lower() for ch in filename if ch.isalnum())
        for p in directory.iterdir():
            normalized_name = "".join(ch.lower() for ch in p.name if ch.isalnum())
            if normalized_target and normalized_target == normalized_name:
                candidate = p
                break
            if normalized_target and normalized_target in normalized_name:
                candidate = p
                break
        if candidate is not None:
            break

    if candidate is None or not candidate.exists():
        raise ValueError(f"Local file not found: {filename} in {folder}")

    data = candidate.read_bytes()
    if not data:
        raise ValueError(f"Local file is empty: {candidate}")

    mime = _guess_mime(candidate)
    return data, mime, candidate.name
