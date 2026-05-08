import os
import logging
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

_cached_creds: Credentials | None = None


def get_credentials() -> Credentials:
    """Return valid Google OAuth credentials, refreshing or re-authorising as needed."""
    global _cached_creds

    if _cached_creds and _cached_creds.valid:
        return _cached_creds

    creds: Credentials | None = None

    if os.path.exists(GOOGLE_TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)
        except Exception as e:
            logger.warning(f"Could not load token.json: {e}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("Google token refreshed successfully")
            except Exception as e:
                logger.warning(f"Token refresh failed: {e}. Re-authorising...")
                creds = None

        if not creds:
            if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"credentials.json not found at {GOOGLE_CREDENTIALS_FILE}. "
                    "Download it from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
            logger.info("New Google OAuth token obtained")

        with open(GOOGLE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    _cached_creds = creds
    return creds
