from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import Settings, load_settings
from errors import AuthError


def get_credentials(settings: Settings | None = None) -> Credentials:
    settings = settings or load_settings()
    token_path = settings.resolve(settings.google.token_path)

    if not token_path.exists():
        raise AuthError("Not authenticated — run `cvdocs auth login` first.")

    creds = Credentials.from_authorized_user_file(str(token_path), settings.google.scopes)

    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds, token_path)
        return creds

    raise AuthError("Stored credentials are invalid — run `cvdocs auth login` again.")


def login(settings: Settings | None = None) -> Credentials:
    settings = settings or load_settings()
    token_path = settings.resolve(settings.google.token_path)
    creds_path = settings.resolve(settings.google.credentials_path)

    if not creds_path.exists():
        raise AuthError(
            f"No OAuth client file at {creds_path}. Download one from the Google Cloud "
            "console (OAuth client ID, type 'Desktop app') and save it there — see README."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), settings.google.scopes)
    creds = flow.run_local_server(port=0)
    _save_token(creds, token_path)
    return creds


def status(settings: Settings | None = None) -> tuple[bool, list[str]]:
    settings = settings or load_settings()
    token_path = settings.resolve(settings.google.token_path)
    if not token_path.exists():
        return False, []
    creds = Credentials.from_authorized_user_file(str(token_path), settings.google.scopes)
    return creds.valid, list(creds.scopes or [])


def _save_token(creds: Credentials, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
