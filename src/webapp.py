import sys

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
import uvicorn

from auth.router import get_auth_provider
from auth.web import WebAuthProvider
from config import load_settings
from errors import AuthError
import os
from storage.sqlite import SqlitePendingSignInStore

app = FastAPI()


@app.get("/auth/google/login")
def auth_google_login(key: str):
    settings = load_settings()
    expected = os.environ.get(settings.web_service.api_key_env, "")
    if not expected or key != expected:
        return PlainTextResponse("Unauthorized", status_code=401)

    provider = get_auth_provider(settings)
    if not isinstance(provider, WebAuthProvider):
        return PlainTextResponse(
            "This deployment is not configured for hosted-mode connections.", status_code=400
        )

    state, code_verifier = SqlitePendingSignInStore(settings.storage_db_path).start()
    url = provider.build_authorization_url(state, code_verifier)
    return RedirectResponse(url, status_code=302)


@app.get("/auth/google/callback")
def auth_google_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error or not code or not state:
        print(f"auth_google_callback rejected: error={error!r} code={bool(code)} state={bool(state)}", file=sys.stderr)
        return HTMLResponse("<p>Sign-in was not completed.</p>", status_code=400)

    settings = load_settings()
    code_verifier = SqlitePendingSignInStore(settings.storage_db_path).verify_and_consume(state)
    if code_verifier is None:
        return HTMLResponse(
            "<p>This sign-in link has expired or was already used.</p>", status_code=400
        )

    provider = get_auth_provider(settings)
    if not isinstance(provider, WebAuthProvider):
        return PlainTextResponse(
            "This deployment is not configured for hosted-mode connections.", status_code=400
        )

    try:
        creds = provider.exchange_code(code, code_verifier)
    except AuthError as exc:
        print(f"auth_google_callback exchange_code failed: {exc}", file=sys.stderr)
        return HTMLResponse("<p>Sign-in was not completed.</p>", status_code=400)

    provider.storage.save(creds)
    return HTMLResponse("<p>Connected successfully. You can close this window.</p>")


def _check_required_env(settings) -> None:
    required_env_vars = [
        settings.google.web_client_id_env,
        settings.google.web_client_secret_env,
        settings.web_service.api_key_env,
    ]
    missing = [name for name in required_env_vars if not os.environ.get(name)]
    if missing:
        for name in missing:
            print(f"Missing required environment variable: {name}", file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    _check_required_env(load_settings())
    uvicorn.run("webapp:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
