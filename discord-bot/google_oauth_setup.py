import os
from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "keys", "credentials.json")
TOKEN_FILE = os.path.join(BASE_DIR, "keys", "token.json")

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

def main():
    print("=== Google OAuth setup ===")
    print("Using credentials:", os.path.abspath(CLIENT_SECRET_FILE))
    print("Will save token to:", os.path.abspath(TOKEN_FILE))

    if not os.path.exists(CLIENT_SECRET_FILE):
        print("ERROR: credentials.json not found")
        return

    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
        print("Old token deleted.")

    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        SCOPES
    )

    creds = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        prompt="consent"
    )

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print("OAuth completed successfully!")
    print("Token saved to:", os.path.abspath(TOKEN_FILE))
    print("Granted scopes:", creds.scopes)

if __name__ == "__main__":
    main()