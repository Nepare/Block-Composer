import datetime
from urllib.parse import quote

import pytest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from auth.web import WebAuthProvider
from core.config import Settings
from core.errors import AuthError


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
def settings(monkeypatch):
    monkeypatch.setenv("GOOGLE_WEB_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_WEB_CLIENT_SECRET", "test-client-secret")
    s = Settings()
    s.auth.google.web_redirect_uri = "http://localhost:8000/auth/google/callback"
    return s


def test_build_authorization_url_is_well_formed(settings):
    provider = WebAuthProvider(settings, FakeCredentialsStorage())

    url = provider.build_authorization_url(state="xyz", code_verifier="a-code-verifier")

    assert url.startswith("https://accounts.google.com/o/oauth2/auth")
    assert "test-client-id" in url
    assert quote(settings.auth.google.web_redirect_uri, safe="") in url


def test_exchange_code_returns_credentials_on_success(settings, monkeypatch):
    fake_creds = Credentials(
        token="fake-access-token",
        refresh_token="fake-refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="x",
        client_secret="y",
        scopes=settings.auth.google.scopes,
    )

    def fake_fetch_token(self, **kwargs):
        self.credentials = fake_creds
        return {"access_token": "fake-access-token", "refresh_token": "fake-refresh-token"}

    # Flow.credentials is normally read-only; give it a setter for the fake fetch_token.
    monkeypatch.setattr(
        Flow,
        "credentials",
        property(
            lambda self: self.__dict__.get("credentials"),
            lambda self, value: self.__dict__.__setitem__("credentials", value),
        ),
    )
    monkeypatch.setattr(Flow, "fetch_token", fake_fetch_token)

    provider = WebAuthProvider(settings, FakeCredentialsStorage())

    result = provider.exchange_code("some-code", code_verifier="a-code-verifier")

    assert isinstance(result, Credentials)
    assert result.token == "fake-access-token"
    assert result.refresh_token == "fake-refresh-token"


def test_exchange_code_wraps_a_rejected_response_in_auth_error(settings, monkeypatch):
    def fake_fetch_token(self, **kwargs):
        raise Exception("invalid_grant")

    monkeypatch.setattr(Flow, "fetch_token", fake_fetch_token)
    provider = WebAuthProvider(settings, FakeCredentialsStorage())

    with pytest.raises(AuthError):
        provider.exchange_code("bad-code", code_verifier="a-code-verifier")


def test_exchange_code_sends_the_same_code_verifier_build_authorization_url_used(settings, monkeypatch):
    """build_authorization_url and exchange_code each construct their own Flow instance,
    so the caller must round-trip the same code_verifier through both."""
    captured = {}

    def fake_fetch_token(self, **kwargs):
        captured["code_verifier"] = self.code_verifier
        self.credentials = Credentials(
            token="t", refresh_token="r", token_uri="https://oauth2.googleapis.com/token",
            client_id="x", client_secret="y", scopes=settings.auth.google.scopes,
        )
        return {}

    monkeypatch.setattr(
        Flow,
        "credentials",
        property(
            lambda self: self.__dict__.get("credentials"),
            lambda self, value: self.__dict__.__setitem__("credentials", value),
        ),
    )
    monkeypatch.setattr(Flow, "fetch_token", fake_fetch_token)

    provider = WebAuthProvider(settings, FakeCredentialsStorage())
    provider.build_authorization_url(state="xyz", code_verifier="the-real-code-verifier")
    provider.exchange_code("some-code", code_verifier="the-real-code-verifier")

    assert captured["code_verifier"] == "the-real-code-verifier"


def test_get_credentials_with_no_stored_connection_raises_auth_error(settings):
    provider = WebAuthProvider(settings, FakeCredentialsStorage(None))

    with pytest.raises(AuthError):
        provider.get_credentials()


def test_get_credentials_refreshes_and_persists_an_expired_token(settings):
    creds = Credentials(
        token="stale",
        refresh_token="r",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="x",
        client_secret="y",
        scopes=settings.auth.google.scopes,
        expiry=_expired_time(),
    )
    assert creds.expired

    def fake_refresh(request):
        creds.token = "fresh"
        creds.expiry = None

    creds.refresh = fake_refresh
    storage = FakeCredentialsStorage(creds)
    provider = WebAuthProvider(settings, storage)

    result = provider.get_credentials()

    assert result.token == "fresh"
    assert storage.saved == [creds]


def test_status_with_no_stored_token_returns_false_and_empty_scopes(settings):
    provider = WebAuthProvider(settings, FakeCredentialsStorage(None))

    assert provider.status() == (False, [])


def test_status_with_valid_stored_token_returns_true_and_scopes(settings):
    creds = Credentials(
        token="valid",
        refresh_token="r",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="x",
        client_secret="y",
        scopes=settings.auth.google.scopes,
    )
    provider = WebAuthProvider(settings, FakeCredentialsStorage(creds))

    valid, scopes = provider.status()

    assert valid is True
    assert scopes == list(settings.auth.google.scopes)
