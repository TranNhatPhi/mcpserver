"""One-time Google Drive authorization.

Run this once to grant the server read-only access to your Google Drive:

    .venv/bin/python drive_auth.py

It needs `credentials.json` (an OAuth *Desktop app* client downloaded from
Google Cloud Console) in the project root. It opens a browser for you to sign
in, then writes `token.json` (containing a refresh token) that the server uses
from then on. Re-run only if you revoke access or change scopes.
"""

import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
CREDENTIALS_PATH = os.environ.get("MCP_DRIVE_CREDENTIALS", "credentials.json")
TOKEN_PATH = os.environ.get("MCP_DRIVE_TOKEN", "token.json")


def main() -> None:
    if not os.path.isfile(CREDENTIALS_PATH):
        raise SystemExit(
            f"Missing {CREDENTIALS_PATH}. Download an OAuth 'Desktop app' client "
            "from Google Cloud Console (APIs & Services > Credentials) and save it "
            f"as {CREDENTIALS_PATH} in this folder."
        )
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    # Opens a browser; falls back to console if no browser is available.
    creds = flow.run_local_server(port=0)
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())
    print(f"Authorized. Saved {TOKEN_PATH}. The server can now read your Drive.")


if __name__ == "__main__":
    main()
