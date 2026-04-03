import os
from datetime import timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    VN_TZ = timezone(timedelta(hours=7))

DB_PATH = os.getenv("DEADLINES_DB", "data/deadlines.db")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SQLITE_TIMEOUT = float(os.getenv("DEADLINES_SQLITE_TIMEOUT", "30"))

GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
GOOGLE_OAUTH_TOKEN_FILE = os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "keys/token.json")
GOOGLE_OAUTH_CLIENT_SECRET_FILE = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_FILE", "keys/credentials.json")
GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "https://localhost/oauth2callback")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
DEADLINE_ALLOW_GLOBAL_GOOGLE_FALLBACK = os.getenv("DEADLINE_ALLOW_GLOBAL_GOOGLE_FALLBACK", "1") == "1"
DEADLINE_TOKEN_ENCRYPTION_KEY = os.getenv("DEADLINE_TOKEN_ENCRYPTION_KEY", "")

GOOGLE_USER_SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

GOOGLE_DEBUG = os.getenv("GOOGLE_DEBUG", "1") == "1"
GOOGLE_SUPPORTS_ALL_DRIVES = os.getenv("GOOGLE_SUPPORTS_ALL_DRIVES", "1") == "1"
DEADLINE_PUBLIC_DOC_EDIT = os.getenv("DEADLINE_PUBLIC_DOC_EDIT", "1") == "1"
DEADLINE_LOOP_BATCH_LIMIT = int(os.getenv("DEADLINE_LOOP_BATCH_LIMIT", "25"))
DEADLINE_RESTORE_VIEWS_LIMIT = int(os.getenv("DEADLINE_RESTORE_VIEWS_LIMIT", "2000"))
DEADLINE_LIST_LIMIT = int(os.getenv("DEADLINE_LIST_LIMIT", "50"))
DEADLINE_MAX_ACTIVE_PER_GUILD = int(os.getenv("DEADLINE_MAX_ACTIVE_PER_GUILD", "300"))


def abs_path(path: str | None) -> str | None:
    if not path:
        return None
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)
