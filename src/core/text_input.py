"""Resolve free text that may arrive inline or via a file. Not tied to Typer/CLI —
a future non-CLI caller (e.g. a web handler) can pass a string already in memory (a form
field) and/or a Path already on disk (an uploaded file) and get the same behavior.
"""

from pathlib import Path

from core.errors import InputError


def resolve_text_input(
    inline: str | None,
    file: Path | None,
    *,
    flag_inline: str,
    flag_file: str,
    required: bool = True,
) -> str:
    """Exactly one of `inline`/`file` when required. `flag_inline`/`flag_file` are only
    used in error text, so callers with different UI vocab can supply their own labels."""
    has_inline = bool(inline)
    has_file = file is not None
    if has_inline and has_file:
        raise InputError(f"Pass either {flag_inline} or {flag_file}, not both.")
    if has_file:
        if not file.exists():
            raise InputError(f"{flag_file} file not found: {file}")
        return file.read_text(encoding="utf-8").strip()
    if has_inline:
        return inline.strip()
    if required:
        raise InputError(f"Provide {flag_inline} or {flag_file}.")
    return ""
