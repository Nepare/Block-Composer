import re

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from auth.router import get_auth_provider
from config import Settings, load_settings
from errors import DocsApiError

_DOC_ID_RE = re.compile(r"/document/d/([a-zA-Z0-9_-]+)")


def resolve_doc_id(id_or_url: str) -> str:
    match = _DOC_ID_RE.search(id_or_url)
    return match.group(1) if match else id_or_url


def get_document(doc_id: str, settings: Settings | None = None) -> dict:
    """The only place raw Docs API JSON is ever touched — everything downstream of
    dissection works on flat Markdown."""
    settings = settings or load_settings()
    creds = get_auth_provider(settings).get_credentials()
    service = build("docs", "v1", credentials=creds)
    try:
        return service.documents().get(documentId=doc_id).execute()
    except HttpError as exc:
        raise DocsApiError(f"Failed to fetch document {doc_id}: {exc}") from exc
