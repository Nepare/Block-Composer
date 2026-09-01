from urllib.parse import parse_qs, urlparse

import fastapi.testclient
import pytest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from config import Settings
from storage.sqlite import SqliteCredentialsStorage


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_WEB_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_WEB_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("CVDOCS_API_KEY", "test-shared-secret")
    s = Settings()
    s.storage.backend = "sqlite"
    s.storage.sqlite_path = str(tmp_path / "cvdocs.db")
    s.google.web_redirect_uri = "http://localhost:8000/auth/google/callback"
    return s


@pytest.fixture
def client(settings, monkeypatch):
    import webapp

    monkeypatch.setattr(webapp, "load_settings", lambda: settings)
    return fastapi.testclient.TestClient(webapp.app)


def _patch_fetch_token_success(monkeypatch, creds, captured_code_verifiers=None):
    def fake_fetch_token(self, **kwargs):
        if captured_code_verifiers is not None:
            captured_code_verifiers.append(self.code_verifier)
        self.credentials = creds
        return {"access_token": creds.token, "refresh_token": creds.refresh_token}

    monkeypatch.setattr(
        Flow,
        "credentials",
        property(
            lambda self: self.__dict__.get("credentials"),
            lambda self, value: self.__dict__.__setitem__("credentials", value),
        ),
    )
    monkeypatch.setattr(Flow, "fetch_token", fake_fetch_token)


def _patch_fetch_token_failure(monkeypatch):
    def fake_fetch_token(self, **kwargs):
        raise Exception("invalid_grant")

    monkeypatch.setattr(Flow, "fetch_token", fake_fetch_token)


def _state_from_login(client):
    response = client.get(
        "/auth/google/login", params={"key": "test-shared-secret"}, follow_redirects=False
    )
    location = response.headers["location"]
    query = parse_qs(urlparse(location).query)
    return query["state"][0]


def test_login_redirects_to_google_with_correct_key(client):
    response = client.get(
        "/auth/google/login", params={"key": "test-shared-secret"}, follow_redirects=False
    )

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/auth")
    assert "test-client-id" in location


def test_full_round_trip_persists_credentials(client, settings, monkeypatch):
    state = _state_from_login(client)

    fake_creds = Credentials(
        token="fake-access-token",
        refresh_token="fake-refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="x",
        client_secret="y",
        scopes=settings.google.scopes,
    )
    captured_code_verifiers = []
    _patch_fetch_token_success(monkeypatch, fake_creds, captured_code_verifiers)

    response = client.get(
        "/auth/google/callback", params={"code": "some-code", "state": state}
    )

    assert response.status_code == 200
    loaded = SqliteCredentialsStorage(settings.storage_db_path).load()
    assert loaded is not None
    assert loaded.token == "fake-access-token"
    assert loaded.refresh_token == "fake-refresh-token"
    # Regression check: the code_verifier that reaches Google's real token endpoint
    # must be non-None — a real Google server rejects a missing one with
    # "invalid_grant: Missing code verifier." (a fake fetch_token that ignores
    # self.code_verifier entirely wouldn't otherwise catch that).
    assert captured_code_verifiers[0] is not None


def test_login_missing_key_is_422(client, settings):
    response = client.get("/auth/google/login", follow_redirects=False)

    assert response.status_code == 422
    from storage.sqlite import SqlitePendingSignInStore

    assert SqlitePendingSignInStore(settings.storage_db_path).verify_and_consume("anything") is None


def test_login_wrong_key_is_401(client, settings):
    response = client.get(
        "/auth/google/login", params={"key": "wrong"}, follow_redirects=False
    )

    assert response.status_code == 401
    from storage.sqlite import SqlitePendingSignInStore

    assert SqlitePendingSignInStore(settings.storage_db_path).verify_and_consume("anything") is None


def test_callback_with_error_leaves_existing_connection_untouched(client, settings):
    existing_creds = Credentials(
        token="existing-token",
        refresh_token="existing-refresh",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="x",
        client_secret="y",
        scopes=settings.google.scopes,
    )
    SqliteCredentialsStorage(settings.storage_db_path).save(existing_creds)

    response = client.get("/auth/google/callback", params={"error": "access_denied"})

    assert response.status_code == 400
    loaded = SqliteCredentialsStorage(settings.storage_db_path).load()
    assert loaded.token == "existing-token"
    assert loaded.refresh_token == "existing-refresh"


def test_callback_with_unknown_state_is_400(client, settings):
    response = client.get(
        "/auth/google/callback", params={"code": "some-code", "state": "never-started"}
    )

    assert response.status_code == 400
    assert SqliteCredentialsStorage(settings.storage_db_path).load() is None


def test_callback_with_failed_exchange_is_400(client, settings, monkeypatch):
    state = _state_from_login(client)
    _patch_fetch_token_failure(monkeypatch)

    response = client.get(
        "/auth/google/callback", params={"code": "bad-code", "state": state}
    )

    assert response.status_code == 400
    assert SqliteCredentialsStorage(settings.storage_db_path).load() is None
