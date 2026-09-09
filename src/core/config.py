import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

def _resolve_project_root() -> Path:
    # A non-editable install (e.g. the Docker image's `pip install .`) copies this file into
    # site-packages, three levels away from anything meaningful — fall back to the working
    # directory (the deployment's WORKDIR) when that's where config.yaml actually lives.
    package_relative = Path(__file__).resolve().parent.parent.parent
    if (package_relative / "config.yaml").exists():
        return package_relative
    cwd = Path.cwd()
    if (cwd / "config.yaml").exists():
        return cwd
    return package_relative


PROJECT_ROOT = _resolve_project_root()


class OpenRouterConfig(BaseModel):
    base_url: str = "https://openrouter.ai/api/v1"
    api_key_env: str = "OPENROUTER_API_KEY"

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    docker_base_url: str = "http://ollama:11434"


class ProviderConfig(BaseModel):
    default: str = "openrouter"


class ModelsConfig(BaseModel):
    # Defaults only apply if config.yaml is missing entirely — it's the actual source of truth.
    generate: str = "openrouter:nvidia/nemotron-3-super-120b-a12b:free"
    mutate: str = "openrouter:nvidia/nemotron-3-super-120b-a12b:free"
    compose: str = "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free"
    naming: str = "openrouter:nvidia/nemotron-3-super-120b-a12b:free"
    keywords: str = "openrouter:nvidia/nemotron-3-super-120b-a12b:free"


class GoogleConfig(BaseModel):
    scopes: list[str] = Field(
        default_factory=lambda: ["https://www.googleapis.com/auth/documents.readonly"]
    )
    credentials_path: str = "credentials/credentials.json"
    token_path: str = "credentials/token.json"
    # Hosted-mode (WebAuthProvider) OAuth client — env var names, never the secrets.
    web_client_id_env: str = "GOOGLE_WEB_CLIENT_ID"
    web_client_secret_env: str = "GOOGLE_WEB_CLIENT_SECRET"
    web_redirect_uri: str = "http://localhost:8000/auth/google/callback"


class WebServiceConfig(BaseModel):
    api_key_env: str = "CVDOCS_API_KEY"


class PromptConstraintsConfig(BaseModel):
    """Paths to per-tool constraint files, appended to that tool's system prompt on every
    call; a missing file is treated as no constraints, not an error."""

    generate: str = "input_prompts/constraints/GENERATE_CONSTRAINTS.md"
    naming: str = "input_prompts/constraints/NAMING_CONSTRAINTS.md"
    mutate: str = "input_prompts/constraints/MUTATE_CONSTRAINTS.md"
    compose: str = "input_prompts/constraints/COMPOSE_CONSTRAINTS.md"
    keywords: str = "input_prompts/constraints/KEYWORDS_CONSTRAINTS.md"


class ComposeConfig(BaseModel):
    """Compose always narrows the block library to keyword-matched blocks before planning
    (see compose.py::_select_candidate_blocks)."""

    keyword_search_top_n: int = 12
    keyword_search_unmatched_reserve: int = 2  # fixed, not proportional to top_n
    keywords_per_category_min: int = 0
    keywords_per_category_max: int = 10  # hard-truncates; min isn't enforced
    plan_max_tokens: int = 4000  # completion-token cap for the compose planner LLM call


class MutateConfig(BaseModel):
    max_tokens: int = 900  # completion-token cap for the mutate LLM call


class GenerateConfig(BaseModel):
    max_tokens: int = 900  # completion-token cap for the generate LLM call


class StorageConfig(BaseModel):
    """Picks the block/result storage backend via storage/router.py's dispatch."""

    backend: Literal["filesystem", "sqlite"] = "filesystem"
    docker_backend: Literal["filesystem", "sqlite"] = "sqlite"
    sqlite_path: str = "output/cvdocs.db"


class LLMConfig(BaseModel):
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)


class PathConfig(BaseModel):
    blocks_dir: str = "output/blocks"
    results_dir: str = "output/results"
    templates_path: str = "templates.yaml"
    sample_blocks_dir: str = "input_prompts/sample_entries"
    logs_dir: str = "output/logs"
    storage: StorageConfig = Field(default_factory=StorageConfig)
    constraints: PromptConstraintsConfig = Field(default_factory=PromptConstraintsConfig)


class BehaviorConfig(BaseModel):
    compose: ComposeConfig = Field(default_factory=ComposeConfig)
    mutate: MutateConfig = Field(default_factory=MutateConfig)
    generate: GenerateConfig = Field(default_factory=GenerateConfig)


class AuthConfig(BaseModel):
    google: GoogleConfig = Field(default_factory=GoogleConfig)
    web_service: WebServiceConfig = Field(default_factory=WebServiceConfig)


class Settings(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    path: PathConfig = Field(default_factory=PathConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)

    def resolve(self, relative: str | Path) -> Path:
        p = Path(relative)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def blocks_path(self) -> Path:
        return self.resolve(self.path.blocks_dir)

    @property
    def results_path(self) -> Path:
        return self.resolve(self.path.results_dir)

    @property
    def templates_file(self) -> Path:
        return self.resolve(self.path.templates_path)

    @property
    def sample_blocks_path(self) -> Path:
        return self.resolve(self.path.sample_blocks_dir)

    @property
    def logs_path(self) -> Path:
        return self.resolve(self.path.logs_dir)

    @property
    def storage_db_path(self) -> Path:
        return self.resolve(self.path.storage.sqlite_path)


def _running_in_docker() -> bool:
    return Path("/.dockerenv").exists()


def load_settings(config_path: Path | str | None = None) -> Settings:
    """CLI flag > .env > config.yaml > defaults. Running inside the hosted Docker deployment
    is detected directly (not read from config or env) and swaps in the docker_* values."""
    load_dotenv(PROJECT_ROOT / ".env")
    path = Path(config_path) if config_path else PROJECT_ROOT / "config.yaml"
    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    settings = Settings.model_validate(data)
    if _running_in_docker():
        settings.llm.ollama.base_url = settings.llm.ollama.docker_base_url
        settings.path.storage.backend = settings.path.storage.docker_backend
    return settings
