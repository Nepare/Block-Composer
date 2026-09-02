import datetime

import pytest

from auth.installed_app import InstalledAppAuthProvider
from core.config import Settings
from core.errors import AuthError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


def _expired_time():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(hours=1)


class FakeCredentialsStorage:
    def __init__(self, creds: Credentials | None = None):
        self._creds = creds
        self.saved: list[Credentials] = []

    def save(self, creds: Credentials) -> None:
        self.saved.append(creds)
        self._creds = creds

    def load(self) -> Credentials | None:
        return self._creds


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.auth.google.token_path = str(tmp_path / "token.json")
    s.auth.google.credentials_path = str(tmp_path / "credentials.json")
    return s


def test_get_credentials_returns_valid_stored_token(settings):
    creds = Credentials(token="abc", scopes=["s1"])
    storage = FakeCredentialsStorage(creds)
    provider = InstalledAppAuthProvider(settings, storage)

    result = provider.get_credentials()

    assert result is creds
    assert storage.saved == []


def test_get_credentials_refreshes_and_persists_an_expired_token(settings, monkeypatch):
    creds = Credentials(token="stale", refresh_token="r", scopes=["s1"], expiry=_expired_time())
    assert creds.expired

    def fake_refresh(request):
        creds.token = "fresh"
        creds.expiry = None

    monkeypatch.setattr(creds, "refresh", fake_refresh)
    storage = FakeCredentialsStorage(creds)
    provider = InstalledAppAuthProvider(settings, storage)

    result = provider.get_credentials()

    assert result.token == "fresh"
    assert storage.saved == [creds]


def test_get_credentials_with_no_stored_token_raises_auth_error(settings):
    provider = InstalledAppAuthProvider(settings, FakeCredentialsStorage(None))

    with pytest.raises(AuthError):
        provider.get_credentials()


def test_login_with_no_credentials_file_raises_auth_error_mentioning_where_to_get_one(settings):
    provider = InstalledAppAuthProvider(settings, FakeCredentialsStorage(None))

    with pytest.raises(AuthError, match="Google Cloud"):
        provider.login()


def test_login_only_saves_after_run_local_server_succeeds(settings, monkeypatch):
    creds_path = settings.resolve(settings.auth.google.credentials_path)
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    creds_path.write_text("{}", encoding="utf-8")

    new_creds = Credentials(token="new", scopes=["s1"])

    class FakeFlow:
        def run_local_server(self, port=0):
            return new_creds

    monkeypatch.setattr(
        InstalledAppFlow, "from_client_secrets_file", classmethod(lambda cls, *a, **k: FakeFlow())
    )
    storage = FakeCredentialsStorage(None)
    provider = InstalledAppAuthProvider(settings, storage)

    result = provider.login()

    assert result is new_creds
    assert storage.saved == [new_creds]


def test_status_with_no_stored_token_returns_false_and_empty_scopes(settings):
    provider = InstalledAppAuthProvider(settings, FakeCredentialsStorage(None))

    assert provider.status() == (False, [])
