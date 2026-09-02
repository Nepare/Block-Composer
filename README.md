# cvdocs

A configurable block library and composer, sourced from Google Docs. It dissects a source
Google Doc into reusable **blocks** (flat Markdown files with YAML frontmatter), lets you
generate new blocks or mutate existing ones with an LLM, and composes brand-new documents
from a natural-language request by reusing, adapting, or generating blocks as needed.

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
Running as a **hosted deployment** (Docker, optional — see [section 4](#4-hosted-deployment-optional--docker))
needs its own, separate Google OAuth client plus one more secret; local CLI use never
touches those.

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
3. Copy `.env.example` to `.env` (gitignored) and set:
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

### 4. Hosted deployment (optional — Docker)

Running `cvdocs` as a Docker container (`storage.backend: sqlite`) uses a *different*
Google connection method than the local CLI — a browser-based OAuth flow served over HTTP,
since there's no local machine for a browser popup to talk to. This needs its own Google
OAuth client (a **Web application** client, not the Desktop-app one from section 1) plus a
secret of its own:

1. In the same Google Cloud project as section 1, go to **APIs & Services → Credentials**
   → **Create Credentials → OAuth client ID** → Application type **Web application**.
   Under **Authorized redirect URIs**, add `http://localhost:8000/auth/google/callback`
   (or whatever `google.web_redirect_uri` is set to in `config.yaml`, if you change the
   port/host). Create, then copy the **Client ID** and **Client secret**.
2. Pick a long, random value for the shared authorization credential that gates the
   sign-in link (e.g. `openssl rand -hex 32`) — this is what stops a stranger who finds the
   URL from starting a connection attempt against your deployment.
3. Copy `.env.example` to `.env` and fill in `GOOGLE_WEB_CLIENT_ID`,
   `GOOGLE_WEB_CLIENT_SECRET`, and `CVDOCS_API_KEY` (the value from step 2), alongside
   `OPENROUTER_API_KEY` from section 2.
4. `docker compose up --build`, then visit
   `http://localhost:8000/auth/google/login?key=<your CVDOCS_API_KEY>` in a browser to
   connect. `docker compose exec app cvdocs auth status` confirms it from inside the
   container.

This is a single shared connection for the whole deployment (not one per visiting user),
and is entirely independent of the local CLI's own connection from section 1 — connecting
one doesn't connect the other.

#### Running `generate`/`mutate` over HTTP

Once the service is running, `generate` and `mutate` are also reachable over HTTP, gated by
the same `?key=<CVDOCS_API_KEY>` credential as `/auth/google/login`:

- `POST /generate/start` / `POST /mutate/start` — same inputs as the CLI's `generate`/`mutate`
  commands (JSON body), return `{"job_id": "..."}` immediately rather than blocking until the
  LLM call finishes.
- `GET /generate/stream/{job_id}` / `GET /mutate/stream/{job_id}` — a Server-Sent Events stream
  of that run's progress, ending in one final `event: complete` line with the outcome (the
  produced block's id, or an error). Reconnecting after a run has already finished still
  replays its full history. Neither tool has a cancel endpoint — each is a single short LLM
  call chain, not worth interrupting mid-flight.

```
curl -X POST "http://localhost:8000/generate/start?key=<CVDOCS_API_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"criteria": "a small lighthouse keeper role"}'
# -> {"job_id": "<id>"}

curl -N "http://localhost:8000/generate/stream/<id>?key=<CVDOCS_API_KEY>"
```

## Usage

```
cvdocs auth login                                    # once
cvdocs dissect <google-doc-url>                       # populate output/blocks/

cvdocs blocks list                                    # see what's there
cvdocs blocks list --tag <tag>
cvdocs blocks list --query <text>                      # substring search over name/body
cvdocs blocks show <block-id>

cvdocs generate --criteria "<what you want>"           # new block from scratch
cvdocs generate -f criteria.md                          # ...or read criteria from a file
cvdocs mutate <block-id> --criteria "<how to change it>"  # adapt an existing block
cvdocs mutate <block-id> -f criteria.md                  # ...or read criteria from a file

cvdocs compose "<natural-language request>"            # writes output/results/<name>.md
cvdocs compose -f request.md                            # ...or read the request from a file
cvdocs compose "<request>" --use <block-id> --generate "<criteria>"  # pin specific slots
cvdocs compose "<request>" --dry-run                    # show the plan, write nothing
```

`-f`/`--criteria-file` (`generate`/`mutate`) and `-f`/`--request-file` (`compose`) read a
UTF-8 `.txt`/`.md` file instead of an inline argument — useful for longer or multi-line
text. Pass either the inline form or the file, never both.

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
- `google.web_client_id_env` / `google.web_client_secret_env` / `google.web_redirect_uri` —
  hosted-deployment-only (see [section 4](#4-hosted-deployment-optional--docker)); the first
  two name env vars, never hold secrets themselves.
- `web_service.api_key_env` — names the env var holding the hosted deployment's shared
  authorization credential (see section 4). Also hosted-only.

Secrets never live in `config.yaml` — only the *names* of the env vars that hold them do.
They live in a gitignored `.env` instead: `OPENROUTER_API_KEY` always; `GOOGLE_WEB_CLIENT_ID`,
`GOOGLE_WEB_CLIENT_SECRET`, and `CVDOCS_API_KEY` only if you're running the hosted deployment
(section 4). See `.env.example` for the full list.

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
