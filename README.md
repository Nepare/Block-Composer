# cvdocs

A configurable block library and composer, sourced from Google Docs. It dissects a source
Google Doc into reusable **blocks** (flat Markdown files with YAML frontmatter), lets you
generate new blocks or mutate existing ones with an LLM, and composes brand-new documents
from a natural-language request by reusing, adapting, or generating blocks as needed.

This is a training project for getting hands-on with the modern local/hosted LLM ecosystem
(OpenRouter, Ollama) — not a commercial tool.

## Requirements

- Python 3.11+
- A Google account that can view the source Doc(s) you want to dissect
- A free [OpenRouter](https://openrouter.ai) account (for `generate`/`mutate`/`compose`)
- Optionally, [Ollama](https://ollama.com) installed locally (used by default for the
  cheap `naming` task — see [Configuration](#configuration))

## Install

```
python -m venv .venv
.venv\Scripts\Activate.ps1        # PowerShell; use .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
```

This installs the `cvdocs` command into your virtual environment (see `pyproject.toml` for
the exact dependency list — there's no separate `requirements.txt`).

## Setup

You need two independent things before the CLI is usable: **Google OAuth** (for `dissect`,
read-only) and an **OpenRouter API key** (for `generate`/`mutate`/`compose`). Neither is
related to the other — reading a Doc has nothing to do with which LLM provider you use.

### 1. Google Cloud OAuth (for `dissect`)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new
   project (any name).
2. **APIs & Services → Library** → search "Google Docs API" → **Enable**. (The Drive API
   is not needed — `cvdocs` never writes to Drive, only reads a Doc's content.)
3. **APIs & Services → OAuth consent screen** → User type **External** → fill the required
   fields → leave publishing status as **Testing** → under "Test users," add the Google
   account that can view the Doc(s) you'll dissect (this must be the account you'll
   actually sign in with in step 5).
4. **APIs & Services → Credentials** → **Create Credentials → OAuth client ID** →
   Application type **Desktop app** → Create → **Download JSON**.
5. Save that downloaded file as `credentials/credentials.json` in the project root (that
   exact path is what `config.yaml` points at; the file is gitignored).
6. Run:
   ```
   cvdocs auth login
   ```
   This opens a browser for you to sign in and consent, then caches
   `credentials/token.json` (also gitignored) and refreshes it silently afterward. Verify
   with `cvdocs auth status`.

Since the app stays in **Testing** mode (fine for personal use — no Google verification
review needed), tokens for test users expire after about 7 days; just run
`cvdocs auth login` again when that happens.

**If Google's OAuth setup asks for an "Application home page"**: this only matters for
brand verification (showing a custom name/logo to strangers), which a personal Testing-mode
app never needs. Any live URL works — a GitHub repo page for this project is a normal
choice if you push it there.

### 2. OpenRouter (for `generate`/`mutate`/`compose`)

1. Sign up at [openrouter.ai](https://openrouter.ai) (Google/GitHub/email, no card needed).
2. Go to [openrouter.ai/keys](https://openrouter.ai/keys) → **Create Key** → copy it
   (starts with `sk-or-v1-...`).
3. Create a `.env` file in the project root (gitignored) with:
   ```
   OPENROUTER_API_KEY=sk-or-v1-...
   ```

That's it — the model this project defaults to (`minimax/minimax-m3:free`) costs $0 to
call; the key just identifies you for OpenRouter's free-tier rate limits (20 requests/min,
50/day until you've ever spent $10 on the platform, then 1000/day).

### 3. Ollama (optional, for the local `naming` task)

`config.yaml` routes the cheap block/variant-naming task to a local model by default. If
you don't want to install Ollama, just point it back at OpenRouter instead:

```yaml
models:
  naming: openrouter:minimax/minimax-m3:free
```

To use it as shipped:
1. Install from [ollama.com](https://ollama.com) (or `winget install Ollama.Ollama` on
   Windows) and make sure `ollama serve` is running (the installer starts it automatically).
2. `ollama pull qwen3:1.7b`

No dedicated GPU is required — this is a small model that runs fine on CPU.

## Usage

```
cvdocs auth login                                    # once
cvdocs dissect <google-doc-url>                       # populate output/blocks/

cvdocs blocks list                                    # see what's there
cvdocs blocks list --tag <tag>
cvdocs blocks list --query <text>                      # substring search over name/body
cvdocs blocks show <block-id>

cvdocs generate --criteria "<what you want>"           # new block from scratch
cvdocs mutate <block-id> --criteria "<how to change it>"  # adapt an existing block

cvdocs compose "<natural-language request>"            # writes output/results/<name>.md
cvdocs compose "<request>" --use <block-id> --generate "<criteria>"  # pin specific slots
cvdocs compose "<request>" --dry-run                    # show the plan, write nothing
```

Every LLM-taking command accepts `--model provider:model-id` to override the configured
default for that one call, e.g. `--model openrouter:z-ai/glm-5.3` or
`--model ollama:qwen3:4b`.

## Configuration

`config.yaml` (committed — no secrets live in it) controls:

- `blocks_dir` / `results_dir` — default `output/blocks`, `output/results`
- `templates_path` — see `templates.yaml`, which declares the shape of a "block" inside a
  source Doc (the marker row, which column is which, field-label conventions). Dissection
  is fully deterministic against a doc matching that shape — no LLM calls at all.
- `models.*` — which `provider:model-id` handles each task (`generate`, `mutate`,
  `compose`, `naming`). Mix and match freely — e.g. push the expensive planning work to a
  strong hosted model while keeping cheap tasks fully local and free.
- `sample_blocks_dir` — default `input_prompts/sample_entries`, the fallback style
  examples `generate` learns from when the block library is still empty.
- `constraints.*` — paths to the `input_prompts/constraints/*.md` files (see below).

The only secret, `OPENROUTER_API_KEY`, lives in a gitignored `.env`, never in `config.yaml`.

## `input_prompts/constraints/`

Four files — `GENERATE_CONSTRAINTS.md`, `NAMING_CONSTRAINTS.md`, `MUTATE_CONSTRAINTS.md`,
`COMPOSE_CONSTRAINTS.md` — work like `CLAUDE.md`/`AGENTS.md`: whatever you write in one is
appended to that tool's system prompt on every call. Use them for negative constraints
("don't do X") specific to your own use of the tool. Empty by default; a missing file is
simply treated as no constraints, never an error.

## Tests

```
pytest
```

All LLM calls are mocked in the test suite (`tests/fakes.py`) — running the tests never
hits OpenRouter, Ollama, or the Google Docs API.
