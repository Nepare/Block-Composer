"""AuthProvider Protocol — the shared boundary between "how do we get valid Google
credentials" and everything that consumes them (today: docs_api.py, the only caller).
Callers never need to know which flow produced a valid Credentials object, only that one
is available. See contracts/auth-provider.md (specs/001-google-oauth-web-flow) for the
full contract this Protocol satisfies.
"""

from typing import Protocol

from google.oauth2.credentials import Credentials


class AuthProvider(Protocol):
    def get_credentials(self) -> Credentials: ...
