"""
drive_service.py
In-memory Google Drive file streaming. NEVER writes files to disk.
Supports both single file links and folder links.
"""
import io
import re
import logging
from typing import Optional, Tuple, List, Dict

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

from auth import get_credentials

logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp",
    "image/gif", "image/bmp", "image/tiff",
    "application/pdf",
}

GOOGLE_APPS_MIME = "application/vnd.google-apps"

# Patterns ordered from most-specific to least-specific
_FOLDER_PATTERNS = [
    r"drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)",
    r"/folders/([a-zA-Z0-9_-]+)",
]
_FILE_PATTERNS = [
    r"/d/([a-zA-Z0-9_-]+)",
    r"open\?id=([a-zA-Z0-9_-]+)",
    r"[?&]id=([a-zA-Z0-9_-]+)",
]


def get_drive_service():
    creds = get_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ─────────────────────────────────────────────────────────────────────────────
# URL parsing
# ─────────────────────────────────────────────────────────────────────────────

def extract_drive_id(url: str) -> Optional[Dict]:
    """
    Parse any Google Drive URL and return {"type": "file"|"folder", "id": ...}.
    Supports:
      - File links: https://drive.google.com/file/d/{FILE_ID}/view
      - Folder links: https://drive.google.com/drive/folders/{FOLDER_ID}
      - Short forms with ?id= parameter
    Returns None if URL is invalid or not a Drive link.
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if "drive.google.com" not in url and "docs.google.com" not in url:
        return None

    # Folder first (before file, because folder URLs also contain /d/ sometimes)
    for pattern in _FOLDER_PATTERNS:
        m = re.search(pattern, url)
        if m:
            return {"type": "folder", "id": m.group(1)}

    for pattern in _FILE_PATTERNS:
        m = re.search(pattern, url)
        if m:
            return {"type": "file", "id": m.group(1)}

    return None


# ─────────────────────────────────────────────────────────────────────────────
# In-memory file streaming
# ─────────────────────────────────────────────────────────────────────────────

def stream_file_to_memory(file_id: str) -> Tuple[bytes, str, str]:
    """
    Stream a Drive file into memory WITHOUT writing to disk.
    Returns (bytes, mime_type, filename).
    Caller is responsible for deleting the bytes after use.
    
    Enforces MAX_FILE_SIZE_MB limit to prevent OOM.
    """
    from config import MAX_FILE_SIZE_MB
    
    drive = get_drive_service()

    metadata = drive.files().get(
        fileId=file_id,
        fields="name,mimeType,size,trashed"
    ).execute()

    if metadata.get("trashed"):
        raise ValueError(f"File {file_id} is in trash")

    filename = metadata.get("name", "unknown")
    mime_type = metadata.get("mimeType", "")
    raw_size = metadata.get("size", 0)
    try:
        file_size_bytes = int(raw_size or 0)
    except Exception:
        file_size_bytes = 0
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024

    # Pre-check file size to prevent OOM
    if file_size_bytes > 0 and file_size_bytes > max_bytes:
        raise ValueError(
            f"File '{filename}' is {file_size_bytes / 1024 / 1024:.1f}MB, "
            f"exceeds limit of {MAX_FILE_SIZE_MB}MB"
        )

    # Google Docs/Slides/Sheets → export as PDF
    if mime_type.startswith(GOOGLE_APPS_MIME):
        request = drive.files().export_media(
            fileId=file_id,
            mimeType="application/pdf"
        )
        mime_type = "application/pdf"
    else:
        request = drive.files().get_media(fileId=file_id)

    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request, chunksize=4 * 1024 * 1024)

    done = False
    bytes_downloaded = 0
    while not done:
        _, done = downloader.next_chunk()
        bytes_downloaded = len(buf.getvalue())
        
        # Safety check during download to catch oversized files
        if bytes_downloaded > max_bytes:
            buf.close()
            raise ValueError(
                f"File '{filename}' exceeded {MAX_FILE_SIZE_MB}MB during download "
                f"({bytes_downloaded / 1024 / 1024:.1f}MB downloaded)"
            )

    file_bytes = buf.getvalue()
    buf.close()  # Release buffer immediately

    logger.info(f"Streamed '{filename}' ({len(file_bytes):,} bytes) into memory")
    return file_bytes, mime_type, filename


# ─────────────────────────────────────────────────────────────────────────────
# Folder listing
# ─────────────────────────────────────────────────────────────────────────────

def list_folder_files(folder_id: str) -> List[Dict]:
    """
    List all supported files inside a Drive folder (non-recursive).
    Returns [{"id": ..., "name": ..., "mimeType": ...}].
    """
    drive = get_drive_service()
    files: List[Dict] = []
    page_token: Optional[str] = None

    while True:
        try:
            params: Dict = {
                "q": f"'{folder_id}' in parents and trashed=false",
                "fields": "nextPageToken, files(id, name, mimeType)",
                "pageSize": 100,
                "orderBy": "createdTime",
            }
            if page_token:
                params["pageToken"] = page_token

            result = drive.files().list(**params).execute()

            for f in result.get("files", []):
                mime = f.get("mimeType", "")
                is_supported = (
                    mime in SUPPORTED_MIME_TYPES
                    or mime.startswith("image/")
                    or mime.startswith(GOOGLE_APPS_MIME)
                )
                if is_supported:
                    files.append(f)

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        except HttpError as e:
            logger.error(f"Drive API error listing folder {folder_id}: {e}")
            break

    logger.info(f"Folder {folder_id}: found {len(files)} supported files")
    return files
