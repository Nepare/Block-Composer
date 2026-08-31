from config import Settings

_TASKS = ("generate", "naming", "mutate", "compose")


def load(settings: Settings, task: str) -> str:
    """Read the CLAUDE.md/AGENTS.md-style constraints file for one tool (generate/naming/
    mutate/compose), resolved against the project root. A missing or empty file just means
    no constraints for that call — never an error, since these are optional and the user
    may not have written any yet."""
    if task not in _TASKS:
        raise ValueError(f"Unknown constraints task {task!r}, expected one of {_TASKS}")
    relative = getattr(settings.constraints, task)
    path = settings.resolve(relative)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()
