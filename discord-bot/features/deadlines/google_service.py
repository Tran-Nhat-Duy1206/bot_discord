import csv
import io

import discord
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build

from .config import (
    DEADLINE_ALLOW_GLOBAL_GOOGLE_FALLBACK,
    DEADLINE_PUBLIC_DOC_EDIT,
    GOOGLE_DRIVE_FOLDER_ID,
    GOOGLE_SUPPORTS_ALL_DRIVES,
)
from .db import db_connect
from .oauth_service import _google_creds, _get_service_account_creds, get_user_google_creds, _log_google_error


def _get_creds_with_fallback(scopes: list[str], user_id: int | None = None):
    if user_id:
        try:
            creds, _ = get_user_google_creds(user_id, scopes)
            if creds:
                return creds
        except Exception:
            pass

    if DEADLINE_ALLOW_GLOBAL_GOOGLE_FALLBACK:
        return _get_service_account_creds(scopes)

    return None


def _build_drive_service(creds):
    return build("drive", "v3", credentials=creds)


def create_deadline_sheet(title: str, creds: UserCredentials | None = None, user_id: int | None = None) -> tuple[str | None, str | None]:
    try:
        if creds is None:
            if user_id:
                creds, _ = get_user_google_creds(user_id, ["https://www.googleapis.com/auth/drive"])
            else:
                creds = _google_creds(["https://www.googleapis.com/auth/drive"])
        drive = _build_drive_service(creds)

        metadata: dict[str, object] = {
            "name": title,
            "mimeType": "application/vnd.google-apps.spreadsheet",
        }
        if GOOGLE_DRIVE_FOLDER_ID:
            metadata["parents"] = [GOOGLE_DRIVE_FOLDER_ID]

        created = drive.files().create(
            body=metadata,
            fields="id, webViewLink",
            supportsAllDrives=GOOGLE_SUPPORTS_ALL_DRIVES,
        ).execute()

        file_id = created.get("id")
        file_link = created.get("webViewLink")

        print("[google][sheet] created:", file_id, file_link)

        if DEADLINE_PUBLIC_DOC_EDIT and file_id:
            try:
                drive.permissions().create(
                    fileId=file_id,
                    body={"type": "anyone", "role": "writer"},
                    supportsAllDrives=GOOGLE_SUPPORTS_ALL_DRIVES,
                ).execute()
                print("[google][sheet] public writer permission added")
            except Exception as error:
                _log_google_error("create_deadline_sheet.permission", error)

        return file_id, file_link

    except Exception as error:
        _log_google_error("create_deadline_sheet", error)
        return None, None


def create_deadline_doc(title: str, creds: UserCredentials | None = None, user_id: int | None = None) -> tuple[str | None, str | None]:
    try:
        if creds is None:
            if user_id:
                creds, _ = get_user_google_creds(user_id, ["https://www.googleapis.com/auth/drive"])
            else:
                creds = _google_creds(["https://www.googleapis.com/auth/drive"])
        drive = _build_drive_service(creds)

        metadata: dict[str, object] = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
        }
        if GOOGLE_DRIVE_FOLDER_ID:
            metadata["parents"] = [GOOGLE_DRIVE_FOLDER_ID]

        created = drive.files().create(
            body=metadata,
            fields="id, webViewLink",
            supportsAllDrives=GOOGLE_SUPPORTS_ALL_DRIVES,
        ).execute()

        file_id = created.get("id")
        file_link = created.get("webViewLink")

        print("[google][doc] created:", file_id, file_link)

        if DEADLINE_PUBLIC_DOC_EDIT and file_id:
            try:
                drive.permissions().create(
                    fileId=file_id,
                    body={"type": "anyone", "role": "writer"},
                    supportsAllDrives=GOOGLE_SUPPORTS_ALL_DRIVES,
                ).execute()
                print("[google][doc] public writer permission added")
            except Exception as error:
                _log_google_error("create_deadline_doc.permission", error)

        return file_id, file_link

    except Exception as error:
        _log_google_error("create_deadline_doc", error)
        return None, None


def get_or_create_spreadsheet_id(guild: discord.Guild) -> str | None:
    try:
        _google_creds(["https://www.googleapis.com/auth/drive"])
    except Exception:
        return None

    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT sheet_id FROM guild_config WHERE guild_id=?", (guild.id,))
    row = cur.fetchone()
    if row and row[0]:
        conn.close()
        return row[0]

    try:
        creds = _google_creds([
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/spreadsheets",
        ])
        if creds is None:
            conn.close()
            return None

        sheets = build("sheets", "v4", credentials=creds)
        drive = build("drive", "v3", credentials=creds)

        title = f"Deadlines - {guild.name}"
        spreadsheet = sheets.spreadsheets().create(body={"properties": {"title": title}}, fields="spreadsheetId").execute()
        sheet_id = spreadsheet.get("spreadsheetId")
        if not sheet_id:
            conn.close()
            return None

        if GOOGLE_DRIVE_FOLDER_ID:
            try:
                file_meta = drive.files().get(fileId=sheet_id, fields="parents").execute()
                prev_parents = ",".join(file_meta.get("parents", []))
                drive.files().update(
                    fileId=sheet_id,
                    addParents=GOOGLE_DRIVE_FOLDER_ID,
                    removeParents=prev_parents,
                    fields="id, parents",
                ).execute()
            except Exception:
                pass

        cur.execute("INSERT OR REPLACE INTO guild_config(guild_id, sheet_id) VALUES(?, ?)", (guild.id, sheet_id))
        conn.commit()
        conn.close()
        return sheet_id
    except Exception as error:
        print("[deadline] create spreadsheet error:", repr(error))
        conn.close()
        return None


def export_deadlines_to_sheet(guild: discord.Guild, sheet_id: str) -> str | None:
    try:
        _google_creds(["https://www.googleapis.com/auth/drive"])
    except Exception:
        return None
    try:
        creds = _google_creds(["https://www.googleapis.com/auth/spreadsheets"])
        if creds is None:
            return None
        sheets = build("sheets", "v4", credentials=creds)

        conn = db_connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, due_at, done, role_id, private_channel_id, sheet_link, doc_link, owner_id, created_at, cleaned_up
            FROM deadlines
            WHERE guild_id=?
            ORDER BY done ASC, due_at ASC
            """,
            (guild.id,),
        )
        rows = cur.fetchall()
        conn.close()

        values = [[
            "id",
            "title",
            "due_at",
            "done",
            "role_id",
            "channel_id",
            "sheet_link",
            "doc_link",
            "owner_id",
            "created_at",
            "cleaned_up",
        ]]
        for row in rows:
            values.append([str(item) if item is not None else "" for item in row])

        sheets.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="Deadlines!A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()

        return f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    except Exception as error:
        print("[deadline] export sheet error:", repr(error))
        return None


def export_deadlines_to_sheet_per_deadline_tabs(guild: discord.Guild, sheet_id: str) -> str | None:
    try:
        _google_creds(["https://www.googleapis.com/auth/drive"])
    except Exception:
        return None
    try:
        creds = _google_creds([
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ])
        if creds is None:
            return None
        sheets = build("sheets", "v4", credentials=creds)

        conn = db_connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, due_at, done, role_id, private_channel_id, sheet_link, doc_link, owner_id, created_at, cleaned_up
            FROM deadlines
            WHERE guild_id=?
            ORDER BY done ASC, due_at ASC
            """,
            (guild.id,),
        )
        deadlines = cur.fetchall()

        meta = sheets.spreadsheets().get(
            spreadsheetId=sheet_id,
            fields="sheets(properties(sheetId,title))",
        ).execute()
        existing = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in meta.get("sheets", [])}

        requests = []
        for deadline in deadlines:
            deadline_id = int(deadline[0])
            tab_title = f"DL-{deadline_id}"
            if tab_title not in existing:
                requests.append({"addSheet": {"properties": {"title": tab_title}}})

        if requests:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={"requests": requests},
            ).execute()

        for deadline in deadlines:
            (
                deadline_id,
                title,
                due_at,
                done,
                role_id,
                channel_id,
                sheet_link,
                doc_link,
                owner_id,
                created_at,
                cleaned_up,
            ) = deadline
            tab = f"DL-{int(deadline_id)}"

            cur.execute(
                "SELECT user_id FROM deadline_members WHERE deadline_id=? ORDER BY user_id ASC",
                (deadline_id,),
            )
            members = [str(row[0]) for row in cur.fetchall()]

            values = [
                ["id", "title", "due_at", "done", "role_id", "channel_id", "sheet_link", "doc_link", "owner_id", "created_at", "cleaned_up"],
                [str(deadline_id), str(title), str(due_at), str(done), str(role_id or ""), str(channel_id or ""), str(sheet_link or ""), str(doc_link or ""), str(owner_id), str(created_at), str(cleaned_up)],
                [],
                ["members_user_id"],
            ]
            for user_id in members:
                values.append([user_id])

            sheets.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{tab}!A1",
                valueInputOption="RAW",
                body={"values": values},
            ).execute()

        conn.close()
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    except Exception as error:
        print("[deadline] export per-deadline tabs error:", repr(error))
        return None


def export_deadlines_to_csv_bytes(guild_id: int) -> bytes:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, due_at, done, role_id, private_channel_id, sheet_link, doc_link, owner_id, created_at, cleaned_up
        FROM deadlines
        WHERE guild_id=?
        ORDER BY done ASC, due_at ASC
        """,
        (guild_id,),
    )
    rows = cur.fetchall()
    conn.close()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "title", "due_at", "done", "role_id", "channel_id", "sheet_link", "doc_link", "owner_id", "created_at", "cleaned_up"])
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")
