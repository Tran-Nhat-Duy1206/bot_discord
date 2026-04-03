import os
import sqlite3

from .config import DB_PATH, SQLITE_TIMEOUT


def db_init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT)
    cur = conn.cursor()

    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=5000")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS deadlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            due_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0,

            role_id INTEGER,
            private_channel_id INTEGER,
            google_account_email TEXT,

            sheet_link TEXT,
            sheet_file_id TEXT,
            sheet_message_id INTEGER,

            doc_link TEXT,
            doc_file_id TEXT,
            doc_message_id INTEGER,

            announce_message_id INTEGER,
            cleaned_up INTEGER NOT NULL DEFAULT 0,
            cleaned_at TEXT
        )
        """
    )

    for ddl in (
        "ALTER TABLE deadlines ADD COLUMN sheet_link TEXT",
        "ALTER TABLE deadlines ADD COLUMN sheet_file_id TEXT",
        "ALTER TABLE deadlines ADD COLUMN sheet_message_id INTEGER",
        "ALTER TABLE deadlines ADD COLUMN doc_link TEXT",
        "ALTER TABLE deadlines ADD COLUMN doc_file_id TEXT",
        "ALTER TABLE deadlines ADD COLUMN doc_message_id INTEGER",
        "ALTER TABLE deadlines ADD COLUMN announce_message_id INTEGER",
        "ALTER TABLE deadlines ADD COLUMN cleaned_up INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE deadlines ADD COLUMN cleaned_at TEXT",
        "ALTER TABLE deadlines ADD COLUMN google_account_email TEXT",
    ):
        try:
            cur.execute(ddl)
        except Exception:
            pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            sheet_id TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS deadline_notifs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deadline_id INTEGER NOT NULL,
            notify_at TEXT NOT NULL,
            sent INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_try_at TEXT,
            last_error TEXT
        )
        """
    )

    for ddl in (
        "ALTER TABLE deadline_notifs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE deadline_notifs ADD COLUMN next_try_at TEXT",
        "ALTER TABLE deadline_notifs ADD COLUMN last_error TEXT",
    ):
        try:
            cur.execute(ddl)
        except Exception:
            pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS deadline_members (
            deadline_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY(deadline_id, user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_google_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            google_sub TEXT NOT NULL,
            google_email TEXT NOT NULL,
            token_json TEXT NOT NULL,
            scopes TEXT NOT NULL,
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, google_sub)
        )
        """
    )
    try:
        cur.execute("ALTER TABLE user_google_accounts ADD COLUMN google_sub TEXT")
    except Exception:
        pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_google_oauth_states (
            state TEXT PRIMARY KEY,
            code_verifier TEXT,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_deadlines_guild_done_due ON deadlines(guild_id, done, due_at)",
        "CREATE INDEX IF NOT EXISTS idx_deadline_notifs_due_retry ON deadline_notifs(sent, notify_at, next_try_at)",
        "CREATE INDEX IF NOT EXISTS idx_deadline_notifs_deadline ON deadline_notifs(deadline_id)",
        "CREATE INDEX IF NOT EXISTS idx_deadline_members_user_deadline ON deadline_members(user_id, deadline_id)",
        "CREATE INDEX IF NOT EXISTS idx_user_google_accounts_user_default ON user_google_accounts(user_id, is_default)",
        "CREATE INDEX IF NOT EXISTS idx_user_google_oauth_states_user_created ON user_google_oauth_states(user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_user_google_accounts_user_sub ON user_google_accounts(user_id, google_sub)",
    ):
        cur.execute(ddl)

    conn.commit()
    conn.close()


def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
