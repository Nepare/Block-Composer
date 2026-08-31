import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class OpenRouterConfig(BaseModel):
    base_url: str = "https://openrouter.ai/api/v1"
    api_key_env: str = "OPENROUTER_API_KEY"

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"


class ProviderConfig(BaseModel):
    default: str = "openrouter"


class ModelsConfig(BaseModel):
    # Pinned to a specific free model rather than the "openrouter/free" auto-router alias
    # — see the comment above `models:` in config.yaml for why. These are only used if
    # config.yaml is missing entirely; config.yaml is the actual source of truth.
    generate: str = "openrouter:minimax/minimax-m3:free"
    mutate: str = "openrouter:minimax/minimax-m3:free"
    compose: str = "openrouter:minimax/minimax-m3:free"
    naming: str = "openrouter:minimax/minimax-m3:free"
    local_default: str = "ollama:qwen3-coder-next"


class GoogleConfig(BaseModel):
    scopes: list[str] = Field(
        default_factory=lambda: ["https://www.googleapis.com/auth/documents.readonly"]
    )
    credentials_path: str = "credentials/credentials.json"
    token_path: str = "credentials/token.json"


class PromptConstraintsConfig(BaseModel):
    """Paths to CLAUDE.md/AGENTS.md-style constraint files, one per LLM-using tool. Each
    file's content (if it exists) is appended to that tool's system prompt on every call —
    a place for user-editable negative constraints ("don't do X"). Renameable/movable;
    a missing file is simply treated as no constraints, not an error."""

    generate: str = "prompt_constraints/GENERATE_CONSTRAINTS.md"
    naming: str = "prompt_constraints/NAMING_CONSTRAINTS.md"
    mutate: str = "prompt_constraints/MUTATE_CONSTRAINTS.md"
    compose: str = "prompt_constraints/COMPOSE_CONSTRAINTS.md"


class Settings(BaseModel):
    blocks_dir: str = "output/blocks"
    results_dir: str = "output/results"
    templates_path: str = "templates.yaml"
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    google: GoogleConfig = Field(default_factory=GoogleConfig)
    constraints: PromptConstraintsConfig = Field(default_factory=PromptConstraintsConfig)

    def resolve(self, relative: str | Path) -> Path:
        p = Path(relative)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def blocks_path(self) -> Path:
        return self.resolve(self.blocks_dir)

    @property
    def results_path(self) -> Path:
        return self.resolve(self.results_dir)

    @property
    def templates_file(self) -> Path:
        return self.resolve(self.templates_path)


def load_settings(config_path: Path | str | None = None) -> Settings:
    """CLI flag > env > .env > config.yaml > defaults. CLI-flag overrides are applied by
    callers on top of the returned Settings; env/.env only ever supply OPENROUTER_API_KEY."""
    load_dotenv(PROJECT_ROOT / ".env")
    path = Path(config_path) if config_path else PROJECT_ROOT / "config.yaml"
    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Settings.model_validate(data)
