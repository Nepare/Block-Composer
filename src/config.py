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

    generate: str = "input_prompts/constraints/GENERATE_CONSTRAINTS.md"
    naming: str = "input_prompts/constraints/NAMING_CONSTRAINTS.md"
    mutate: str = "input_prompts/constraints/MUTATE_CONSTRAINTS.md"
    compose: str = "input_prompts/constraints/COMPOSE_CONSTRAINTS.md"


class ComposeConfig(BaseModel):
    """Below keyword_search_min_blocks, compose pastes the whole library into one planning
    prompt (zero extra LLM calls) -- fine for a small library. At or above it, compose
    extracts categorized keywords from the request (one extra call, the `naming` model
    tier) and narrows the planning prompt to the top-scoring blocks plus a small sample of
    unmatched ones, instead of dumping everything in."""

    keyword_search_min_blocks: int = 5
    keyword_search_top_n: int = 12
    # a small, fixed number of zero-scoring blocks always included alongside the top-scoring
    # ones, so a block keyword-matching missed isn't invisible to the planner as a possible
    # mutate/generate gap-filler -- fixed rather than proportional to keyword_search_top_n,
    # since a proportional reserve collapses to 0 for a small request-driven top_n.
    keyword_search_unmatched_reserve: int = 2
    # bounds requested per category (role/environment/responsibilities/domain) in the
    # keyword-extraction prompt -- the model is asked for this range, not hard-enforced on
    # the low end (an LLM can't be forced to invent keywords that aren't there), but the
    # parsed result is truncated to keywords_per_category_max regardless of what comes back.
    keywords_per_category_min: int = 0
    keywords_per_category_max: int = 4


class Settings(BaseModel):
    blocks_dir: str = "output/blocks"
    results_dir: str = "output/results"
    templates_path: str = "templates.yaml"
    sample_blocks_dir: str = "input_prompts/sample_entries"
    logs_dir: str = "output/logs"
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    google: GoogleConfig = Field(default_factory=GoogleConfig)
    constraints: PromptConstraintsConfig = Field(default_factory=PromptConstraintsConfig)
    compose: ComposeConfig = Field(default_factory=ComposeConfig)

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

    @property
    def sample_blocks_path(self) -> Path:
        return self.resolve(self.sample_blocks_dir)

    @property
    def logs_path(self) -> Path:
        return self.resolve(self.logs_dir)


def load_settings(config_path: Path | str | None = None) -> Settings:
    """CLI flag > env > .env > config.yaml > defaults. CLI-flag overrides are applied by
    callers on top of the returned Settings; env/.env only ever supply OPENROUTER_API_KEY."""
    load_dotenv(PROJECT_ROOT / ".env")
    path = Path(config_path) if config_path else PROJECT_ROOT / "config.yaml"
    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Settings.model_validate(data)
