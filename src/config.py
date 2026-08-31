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
    generate: str = "openrouter:openrouter/free"
    mutate: str = "openrouter:openrouter/free"
    compose: str = "openrouter:openrouter/free"
    naming: str = "openrouter:openrouter/free"
    local_default: str = "ollama:qwen3-coder-next"


class GoogleConfig(BaseModel):
    scopes: list[str] = Field(
        default_factory=lambda: ["https://www.googleapis.com/auth/documents.readonly"]
    )
    credentials_path: str = "credentials/credentials.json"
    token_path: str = "credentials/token.json"


class Settings(BaseModel):
    blocks_dir: str = "output/blocks"
    results_dir: str = "output/results"
    templates_path: str = "templates.yaml"
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    google: GoogleConfig = Field(default_factory=GoogleConfig)

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
