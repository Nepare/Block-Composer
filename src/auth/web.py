import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from core.config import Settings
from core.errors import AuthError
from storage.base import CredentialsStorage


class WebAuthProvider:
    def __init__(self, settings: Settings, storage: CredentialsStorage):
        self.settings = settings
        self.storage = storage

    def get_credentials(self) -> Credentials:
        creds = self.storage.load()
        if creds is None:
            raise AuthError("Not connected — complete the Google OAuth web flow first.")
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.storage.save(creds)
            return creds
        raise AuthError("Stored credentials are invalid — reconnect via the Google OAuth web flow.")

    def build_authorization_url(self, state: str, code_verifier: str) -> str:
        flow = self._flow(code_verifier)
        url, _ = flow.authorization_url(access_type="offline", state=state, prompt="consent")
        return url

    def exchange_code(self, code: str, code_verifier: str) -> Credentials:
        flow = self._flow(code_verifier)
        try:
            flow.fetch_token(code=code)
        except Exception as exc:
            raise AuthError(f"Google OAuth token exchange failed: {exc}") from exc
        return flow.credentials

    def _flow(self, code_verifier: str) -> Flow:
        client_id = os.environ.get(self.settings.auth.google.web_client_id_env, "")
        client_secret = os.environ.get(self.settings.auth.google.web_client_secret_env, "")
        client_config = {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self.settings.auth.google.web_redirect_uri],
            }
        }
        return Flow.from_client_config(
            client_config,
            scopes=self.settings.auth.google.scopes,
            redirect_uri=self.settings.auth.google.web_redirect_uri,
            code_verifier=code_verifier,
        )
