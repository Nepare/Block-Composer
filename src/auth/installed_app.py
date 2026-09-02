from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from core.config import Settings
from core.errors import AuthError
from storage.base import CredentialsStorage


class InstalledAppAuthProvider:
    """Local sign-in via InstalledAppFlow.run_local_server, persisted through a CredentialsStorage."""

    def __init__(self, settings: Settings, storage: CredentialsStorage):
        self.settings = settings
        self.storage = storage

    def get_credentials(self) -> Credentials:
        creds = self.storage.load()

        if creds is None:
            raise AuthError("Not authenticated — run `cvdocs auth login` first.")

        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.storage.save(creds)
            return creds

        raise AuthError("Stored credentials are invalid — run `cvdocs auth login` again.")

    def login(self) -> Credentials:
        creds_path = self.settings.resolve(self.settings.auth.google.credentials_path)

        if not creds_path.exists():
            raise AuthError(
                f"No OAuth client file at {creds_path}. Download one from the Google Cloud "
                "console (OAuth client ID, type 'Desktop app') and save it there — see README."
            )

        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), self.settings.auth.google.scopes)
        creds = flow.run_local_server(port=0)
        self.storage.save(creds)
        return creds

    def status(self) -> tuple[bool, list[str]]:
        creds = self.storage.load()
        if creds is None:
            return False, []
        return creds.valid, list(creds.scopes or [])
