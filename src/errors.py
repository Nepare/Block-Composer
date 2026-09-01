class CvdocsError(Exception):
    """Base class for all cvdocs errors."""


class AuthError(CvdocsError):
    """Google OAuth / credential problems."""


class DocsApiError(CvdocsError):
    """Google Docs API request failures."""


class TemplateError(CvdocsError):
    """Problems loading or applying templates.yaml."""


class BlockValidationError(CvdocsError):
    """A block (hand-authored, generated, or mutated) fails basic shape checks."""


class BlockNotFoundError(CvdocsError):
    """No block file found for a given id/filename stem."""


class LLMError(CvdocsError):
    """LLM provider/request failures."""


class InputError(CvdocsError):
    """Bad user-supplied input (e.g. conflicting or missing inline/file arguments)."""


class OperationCancelled(CvdocsError):
    """Raised when a caller-supplied cancel_check() reported True mid-operation."""


class ConfigError(CvdocsError):
    """A config value names something that doesn't exist (e.g. an unknown storage
    backend) — distinct from InputError, which is about malformed CLI/API input rather
    than a bad config setting."""
