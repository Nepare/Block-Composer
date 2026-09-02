"""AuthProvider Protocol — callers get a valid Credentials object without knowing which flow produced it."""

from typing import Protocol

from google.oauth2.credentials import Credentials


class AuthProvider(Protocol):
    def get_credentials(self) -> Credentials: ...
