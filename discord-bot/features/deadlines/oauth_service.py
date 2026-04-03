import json
import os
import traceback
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import (
    DEADLINE_TOKEN_ENCRYPTION_KEY,
    GOOGLE_DEBUG,
    GOOGLE_OAUTH_CLIENT_SECRET_FILE,
    GOOGLE_OAUTH_REDIRECT_URI,
    GOOGLE_OAUTH_TOKEN_FILE,
    GOOGLE_SERVICE_ACCOUNT_FILE,
    GOOGLE_USER_SCOPES,
    VN_TZ,
    abs_path,
)
from .db import db_connect

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:
    Fernet = None
    InvalidToken = Exception


_TOKEN_ENC_PREFIX = "enc:v1:"


def _log_google_error(tag: str, error: Exception):
    if not GOOGLE_DEBUG:
        return
    print(f"[google][{tag}] {type(error).__name__}: {error}")
    traceback.print_exc()
    if isinstance(error, HttpError):
        try:
            print("[google] status:", error.resp.status)
        except Exception:
            pass
        try:
            content = error.content.decode("utf-8", errors="ignore")
            print("[google] content:", content[:2000])
        except Exception:
            print("[google] content(raw):", getattr(error, "content", None))


def _get_fernet():
    key = (DEADLINE_TOKEN_ENCRYPTION_KEY or "").strip()
    if not key:
        return None
    if Fernet is None:
        raise RuntimeError("Thiếu package `cryptography`. Cài để bật token encryption at rest.")
    return Fernet(key.encode("utf-8"))


def _encrypt_token_json(token_json: str) -> str:
    fernet = _get_fernet()
    if fernet is None:
        return token_json
    encrypted = fernet.encrypt(token_json.encode("utf-8")).decode("utf-8")
    return f"{_TOKEN_ENC_PREFIX}{encrypted}"


def _decrypt_token_json(stored_value: str) -> str:
    value = str(stored_value or "")
    if not value.startswith(_TOKEN_ENC_PREFIX):
        return value
    fernet = _get_fernet()
    if fernet is None:
        raise RuntimeError("Token đã mã hóa nhưng chưa cấu hình DEADLINE_TOKEN_ENCRYPTION_KEY.")
    raw = value[len(_TOKEN_ENC_PREFIX) :]
    try:
        return fernet.decrypt(raw.encode("utf-8")).decode("utf-8")
    except InvalidToken as error:
        raise RuntimeError("Không giải mã được token: key sai hoặc dữ liệu lỗi.") from error


def _google_creds(scopes: list[str]):
    token_file = abs_path(GOOGLE_OAUTH_TOKEN_FILE)
    if not token_file or not os.path.exists(token_file):
        raise FileNotFoundError("Thiếu token OAuth. Hãy chạy google_oauth_setup.py trước.")

    creds = UserCredentials.from_authorized_user_file(token_file, scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_file, "w", encoding="utf-8") as file:
            file.write(creds.to_json())
    return creds


def _get_service_account_creds(scopes: list[str]):
    from google.oauth2 import service_account

    sa_file = abs_path(GOOGLE_SERVICE_ACCOUNT_FILE)
    if not sa_file or not os.path.exists(sa_file):
        return None

    try:
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=scopes)
        return creds
    except Exception as error:
        _log_google_error("service_account", error)
        return None


def _google_oauth_flow(scopes: list[str], state: str | None = None, code_verifier: str | None = None):
    client_secret_file = abs_path(GOOGLE_OAUTH_CLIENT_SECRET_FILE)
    if not client_secret_file or not os.path.exists(client_secret_file):
        raise FileNotFoundError("Thiếu credentials OAuth client (keys/credentials.json).")

    kwargs = {}
    if code_verifier:
        kwargs['code_verifier'] = code_verifier
    else:
        kwargs['autogenerate_code_verifier'] = True

    flow = Flow.from_client_secrets_file(
        client_secret_file,
        scopes=scopes,
        state=state,
        **kwargs,
    )
    flow.redirect_uri = GOOGLE_OAUTH_REDIRECT_URI
    return flow


def start_user_google_link(user_id: int) -> tuple[str | None, str | None]:
    try:
        flow = _google_oauth_flow(GOOGLE_USER_SCOPES)
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )

        code_verifier = flow.code_verifier

        conn = db_connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM user_google_oauth_states WHERE user_id=?", (int(user_id),))
        cur.execute(
            "INSERT OR REPLACE INTO user_google_oauth_states(state, code_verifier, user_id, created_at) VALUES(?, ?, ?, ?)",
            (str(state), code_verifier, int(user_id), datetime.now(VN_TZ).isoformat()),
        )
        conn.commit()
        conn.close()
        return auth_url, state
    except Exception as error:
        _log_google_error("start_user_google_link", error)
        return None, None


def _parse_oauth_input(input_value: str) -> tuple[str | None, str | None]:
    raw = (input_value or "").strip()
    if not raw:
        return None, None
    if raw.startswith("http://") or raw.startswith("https://"):
        query = parse_qs(urlparse(raw).query)
        code = (query.get("code") or [None])[0]
        state = (query.get("state") or [None])[0]
        return code, state
    return raw, None


def verify_user_google_link(user_id: int, oauth_input: str, state: str | None = None) -> tuple[bool, str]:
    try:
        code, url_state = _parse_oauth_input(oauth_input)
        if not code:
            return False, "Thiếu code OAuth hợp lệ."

        conn = db_connect()
        cur = conn.cursor()
        cur.execute("SELECT state, code_verifier FROM user_google_oauth_states WHERE user_id=?", (int(user_id),))
        row = cur.fetchone()
        if not row:
            conn.close()
            return False, "Không tìm thấy phiên đăng nhập. Hãy chạy `/deadline_google_login` lại."

        expected_state = str(row[0])
        code_verifier = row[1]
        actual_state = (state or url_state or "").strip()
        if actual_state != expected_state:
            conn.close()
            return False, "State OAuth không khớp. Hãy chạy `/deadline_google_login` lại."

        flow = _google_oauth_flow(GOOGLE_USER_SCOPES, state=expected_state, code_verifier=code_verifier)
        flow.fetch_token(code=code)
        creds = flow.credentials
        if not creds:
            conn.close()
            return False, "Không lấy được credentials từ Google."

        oauth2 = build("oauth2", "v2", credentials=creds)
        info = oauth2.userinfo().get().execute()
        email = str(info.get("email", "")).strip().lower()
        google_sub = str(info.get("sub", "")).strip()
        if not email or not google_sub:
            conn.close()
            return False, "Không lấy được thông tin Google account."

        now_iso = datetime.now(VN_TZ).isoformat()
        scopes = ",".join(sorted(str(scope) for scope in (creds.scopes or GOOGLE_USER_SCOPES)))
        token_json = _encrypt_token_json(creds.to_json())

        cur.execute("SELECT COUNT(1) FROM user_google_accounts WHERE user_id=?", (int(user_id),))
        total_accounts = int((cur.fetchone() or [0])[0])
        is_default = 1 if total_accounts == 0 else 0

        cur.execute(
            """
            INSERT INTO user_google_accounts(user_id, google_sub, google_email, token_json, scopes, is_default, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, google_sub)
            DO UPDATE SET
                google_email=excluded.google_email,
                token_json=excluded.token_json,
                scopes=excluded.scopes,
                updated_at=excluded.updated_at
            """,
            (int(user_id), google_sub, email, token_json, scopes, is_default, now_iso, now_iso),
        )

        cur.execute("DELETE FROM user_google_oauth_states WHERE user_id=?", (int(user_id),))
        conn.commit()
        conn.close()
        return True, email
    except Exception as error:
        _log_google_error("verify_user_google_link", error)
        return False, f"Xác thực thất bại: {type(error).__name__}"


def list_user_google_accounts(user_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT google_sub, google_email, is_default, updated_at
        FROM user_google_accounts
        WHERE user_id=?
        ORDER BY is_default DESC, google_email ASC
        """,
        (int(user_id),),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def set_user_google_default(user_id: int, email: str) -> tuple[bool, str]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM user_google_accounts WHERE user_id=? AND lower(google_email)=lower(?)",
        (int(user_id), str(email)),
    )
    if not cur.fetchone():
        conn.close()
        return False, "Email chưa được liên kết."

    cur.execute("UPDATE user_google_accounts SET is_default=0 WHERE user_id=?", (int(user_id),))
    cur.execute(
        "UPDATE user_google_accounts SET is_default=1, updated_at=? WHERE user_id=? AND lower(google_email)=lower(?)",
        (datetime.now(VN_TZ).isoformat(), int(user_id), str(email)),
    )
    conn.commit()
    conn.close()
    return True, "ok"


def unlink_user_google_account(user_id: int, email: str) -> tuple[bool, str]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT is_default FROM user_google_accounts WHERE user_id=? AND lower(google_email)=lower(?)",
        (int(user_id), str(email)),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, "Email chưa được liên kết."

    was_default = int(row[0]) == 1
    cur.execute(
        "DELETE FROM user_google_accounts WHERE user_id=? AND lower(google_email)=lower(?)",
        (int(user_id), str(email)),
    )
    if was_default:
        cur.execute(
            """
            UPDATE user_google_accounts
            SET is_default=1
            WHERE id=(
                SELECT id FROM user_google_accounts
                WHERE user_id=?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
            )
            """,
            (int(user_id),),
        )
    conn.commit()
    conn.close()
    return True, "ok"


def get_user_google_creds(user_id: int, scopes: list[str], preferred_email: str | None = None):
    conn = db_connect()
    cur = conn.cursor()
    if preferred_email:
        cur.execute(
            """
            SELECT id, token_json, google_email
            FROM user_google_accounts
            WHERE user_id=? AND lower(google_email)=lower(?)
            LIMIT 1
            """,
            (int(user_id), str(preferred_email)),
        )
    else:
        cur.execute(
            """
            SELECT id, token_json, google_email
            FROM user_google_accounts
            WHERE user_id=?
            ORDER BY is_default DESC, updated_at DESC, id DESC
            LIMIT 1
            """,
            (int(user_id),),
        )
    row = cur.fetchone()
    if not row:
        conn.close()
        if preferred_email:
            raise FileNotFoundError(f"Không tìm thấy account Google `{preferred_email}` cho user này.")
        raise FileNotFoundError("Bạn chưa liên kết Google account. Dùng /deadline_google_login trước.")

    acc_id, token_json, email = row
    info = json.loads(_decrypt_token_json(str(token_json)))
    creds = UserCredentials.from_authorized_user_info(info, scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        cur.execute(
            "UPDATE user_google_accounts SET token_json=?, updated_at=? WHERE id=?",
            (_encrypt_token_json(creds.to_json()), datetime.now(VN_TZ).isoformat(), int(acc_id)),
        )
        conn.commit()
    conn.close()
    return creds, str(email)


def import_global_token_for_user(user_id: int) -> tuple[bool, str]:
    try:
        creds = _google_creds(GOOGLE_USER_SCOPES)
    except Exception as error:
        return False, f"Không đọc được token global: {error}"

    email = "imported-global"
    try:
        oauth2 = build("oauth2", "v2", credentials=creds)
        info = oauth2.userinfo().get().execute()
        email = str(info.get("email", email)).strip().lower() or email
    except Exception:
        pass

    now_iso = datetime.now(VN_TZ).isoformat()
    scopes = ",".join(sorted(str(scope) for scope in (creds.scopes or GOOGLE_USER_SCOPES)))
    token_json = _encrypt_token_json(creds.to_json())

    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(1) FROM user_google_accounts WHERE user_id=?", (int(user_id),))
    has_any = int((cur.fetchone() or [0])[0]) > 0
    cur.execute(
        """
        INSERT INTO user_google_accounts(user_id, google_email, token_json, scopes, is_default, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, google_email)
        DO UPDATE SET
            token_json=excluded.token_json,
            scopes=excluded.scopes,
            updated_at=excluded.updated_at
        """,
        (int(user_id), email, token_json, scopes, 0 if has_any else 1, now_iso, now_iso),
    )
    conn.commit()
    conn.close()
    return True, email
