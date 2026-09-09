# Block Composer

A configurable block library and composer, sourced from Google Docs. It dissects a source
Google Doc into reusable **blocks** (flat Markdown files with YAML frontmatter), lets you
generate new blocks or mutate existing ones with an LLM, and composes brand-new documents
from a natural-language request by reusing, adapting, or generating blocks as needed.

## Requirements

`Block Composer` needs:

- A Google account that can view the source Doc(s) you want to dissect
- A free [OpenRouter](https://openrouter.ai) account (for `generate`/`mutate`/`compose`)

Each deployment type below has its own additional requirements.

## Contents

- [Hosted deployment](#hosted-deployment-docker) — Web GUI + HTTP API, run via Docker
- [Local CLI deployment](#local-cli-deployment) — the `cvdocs` command, run on your own machine
- [Configuration](#configuration) — the configuration to fine tune the system

Pick whichever matches how you want to use `cvdocs` — the two are independent, so you only
need to read the section that applies to you.

## Hosted Deployment (Docker)

Run `Block Composer` as a Docker container to serve the Web GUI and HTTP API to others, or from a
server with no local browser to pop an OAuth window on.

### Requirements

In addition to the [common requirements](#requirements) above:

- [Docker](https://www.docker.com) (with Compose)

### Setup

#### Prerequisits

1. Copy `.env.example` to `.env` (gitignored), the variables will be assigned during the setup step.
2. Assign the variables in `.env` using instructions from the next steps.
3. `docker compose build` (see [Usage](#usage) below) builds the image from the `Dockerfile`, pulling 
   everything it needs (Python, Ollama, dependencies) inside the container.

#### 1. OpenRouter (for `generate`/`mutate`/`compose`)

1. Sign up at [openrouter.ai](https://openrouter.ai) (Google/GitHub/email, no card needed).
2. Go to [openrouter.ai/keys](https://openrouter.ai/keys) → **Create Key** → copy it
   (starts with `sk-or-v1-...`).
3. In `.env`, set:
   ```
   OPENROUTER_API_KEY=sk-or-v1-...
   ```

That's it — this project defaults to the configured model; the key just identifies you for 
OpenRouter. Remember: free-tier `:free` models sit behind a shared upstream pool and can
occasionally return a transient 429 (rate-limited) or, less often, get deprecated outright —
if `config.yaml`'s configured model ever fails outright, check [openrouter.ai/models](https://openrouter.ai/models)
(filter by price) for a current `:free` slug to swap in.

#### 2. Ollama (optional, for the cheaper local tasks)

`config.yaml` routes the cheap block/variant-naming task to a local model by default. If
you don't want to install Ollama, just point it back at OpenRouter instead:

```yaml
llm:
  models:
    naming: openrouter:nvidia/nemotron-3-super-120b-a12b:free
```

No installation is needed for the hosted deployment. `docker-compose.yml` runs its own
`ollama` sidecar and an `ollama-pull` step that pulls that model automatically on first
start; the weights are kept in a named volume, so a restart doesn't re-download them.
Change `llm.models.naming` and the next `docker compose up` pulls whatever you set. If it's
not an `ollama:` model at all (e.g. pointed back at OpenRouter per the example above),
`ollama-pull` skips the pull entirely.

#### 3. Google OAuth (for importing from Google Docs)

`cvdocs` needs a Google OAuth connection to read Docs if you want to import Google Docs blocks. 
The hosted deployment uses a browser-based OAuth flow served over HTTP (since there's no 
local machine for a browser popup to talk to), backed by a **Web application** OAuth client and 
a shared authorization credential that gates who can trigger it.

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new
   project (any name).
2. **APIs & Services → Library** → search "Google Docs API" → **Enable**. (The Drive API
   is not needed — `cvdocs` never writes to Drive, only reads a Doc's content.)
3. **APIs & Services → OAuth consent screen** → User type **External** → fill the required
   fields → leave publishing status as **Testing** → under "Test users" add the Google
   account that can view the Doc(s) you'll dissect.
4. **APIs & Services → Credentials** → **Create Credentials → OAuth client ID** →
   Application type **Web application**. Under **Authorized redirect URIs**, add
   `http://localhost:8000/auth/google/callback` (or whatever `auth.google.web_redirect_uri`
   is set to in `config.yaml`, if you change the port/host). 
5. **Create**, then copy the **Client ID** to `GOOGLE_WEB_CLIENT_ID`, and **Client secret**
   to `GOOGLE_WEB_CLIENT_SECRET` in `.env`.

#### 4. Running the whole thing

1. Pick a long, random value for the shared authorization credential that gates the
   sign-in link (e.g. `openssl rand -hex 32`, [Devglan hash generator](https://www.devglan.com/online-tools/openssl-hash-generator) 
   or just think of a random string) — this is what stops a stranger who finds the URL 
   from starting a connection attempt against your deployment.
2. Copy this value into `CVDOCS_API_KEY` in `.env`.
3. `docker compose up --build`, then visit
   `http://localhost:8000/auth/google/login?key=<your CVDOCS_API_KEY>` in a browser to
   connect. `docker compose exec app cvdocs auth status` confirms it from inside the
   container.

This is a single shared connection for the whole deployment (not one per visiting user).
Since the app stays in **Testing** mode (fine for personal use — no Google verification
review needed), the connection expires after about 7 days; just repeat step 7 when that
happens.

### Usage

#### Web GUI

On first visit, paste the shared `CVDOCS_API_KEY` secret into the login screen; it's validated
against `GET /auth/check` and persisted in the browser so subsequent visits skip the prompt.
The Library tab browses/generates/mutates/dissects blocks; the Compose tab drives a composition
from a description to a finished result, with a history sidebar to revisit past ones.

These commands handle the entire process:
```
docker compose build                    # builds the image
docker compose up                       # runs the container
```

#### HTTP

Every route below is gated by the same `?key=<CVDOCS_API_KEY>` credential as
`/auth/google/login`.

```
POST /generate/start                    # start a generate job -> {"job_id"}
POST /mutate/start                      # start a mutate job -> {"job_id"}
POST /dissect/start                     # start a dissect job -> {"job_id"}
POST /compose/start                     # start a compose job -> {"job_id"}
GET  /stream/{job_id}                   # SSE progress + final outcome for any job
POST /cancel/{job_id}                   # cancel a running compose job

GET  /blocks                            # list blocks, optional query/tag filters
GET  /blocks/{id}                       # one block's full content
PUT  /blocks/{id}                       # replace a block's body/tags/schema
DELETE /blocks/{id}                     # delete a block
POST /blocks/{id}/preserve              # lock a block
POST /blocks/{id}/unpreserve            # unlock a block
POST /blocks/clear                      # delete every non-preserved block

GET  /results                           # list saved compose results, optional query filter
GET  /results/{id}                      # one result's full content + slots
DELETE /results/{id}                    # delete a saved result
POST /results/{id}/preserve             # lock a result
POST /results/{id}/unpreserve           # unlock a result
POST /results/{id}/rename               # rename a result
POST /results/clear                     # delete every non-preserved result
```

`generate`/`mutate`/`dissect` take the same inputs as their CLI commands (see
[Local CLI Deployment](#local-cli-deployment) for the full flag list); `compose` takes the
same inputs as its CLI command plus a `specifiers` field (short free text merged into `request`)
and has no filesystem output path or dry-run mode. Unlike the other three, compose is
cancellable and its stream outcome includes the finished document.

```
curl -X POST "http://localhost:8000/generate/start?key=<CVDOCS_API_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"criteria": "a small lighthouse keeper role"}'
# -> {"job_id": "<id>"}

curl -N "http://localhost:8000/stream/<id>?key=<CVDOCS_API_KEY>"
```

## Local CLI Deployment

Run `Block Composer` directly on your own machine via the `cvdocs` command.

### Requirements

In addition to the [common requirements](#requirements) above:

- Python 3.11+
- Optionally, [Ollama](https://ollama.com) installed locally (used by default for the cheap
  `naming` and `keywords` tasks — see [Configuration](#configuration))

### Setup

#### Prerequisits

1. Copy `.env.example` to `.env` (gitignored), the variables will be assigned during the setup step.
2. Assign the variables in `.env` using instructions from the next steps.

#### 1. Install

```
python -m venv .venv
.venv\Scripts\Activate.ps1        # PowerShell; use .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
```

This installs the `cvdocs` command into your virtual environment (see `pyproject.toml` for
the exact dependency list — there's no separate `requirements.txt`).

#### 2. OpenRouter (for `generate`/`mutate`/`compose`)

1. Sign up at [openrouter.ai](https://openrouter.ai) (Google/GitHub/email, no card needed).
2. Go to [openrouter.ai/keys](https://openrouter.ai/keys) → **Create Key** → copy it
   (starts with `sk-or-v1-...`).
3. In `.env`, set:
   ```
   OPENROUTER_API_KEY=sk-or-v1-...
   ```

That's it — this project defaults to the configured model; the key just identifies you for 
OpenRouter. Remember: free-tier `:free` models sit behind a shared upstream pool and can
occasionally return a transient 429 (rate-limited) or, less often, get deprecated outright —
if `config.yaml`'s configured model ever fails outright, check [openrouter.ai/models](https://openrouter.ai/models)
(filter by price) for a current `:free` slug to swap in.

#### 3. Ollama (optional, for the cheaper local tasks)

`config.yaml` routes the cheap block/variant-naming task to a local model by default. If
you don't want to install Ollama, just point it back at OpenRouter instead:

```yaml
llm:
  models:
    naming: openrouter:nvidia/nemotron-3-super-120b-a12b:free
```

1. Install from [ollama.com](https://ollama.com) (or `winget install Ollama.Ollama` on
   Windows) and make sure `ollama serve` is running (the installer starts it automatically).
2. `ollama pull qwen3:1.7b`

No dedicated GPU is required — this is a small model that runs fine on CPU.

#### 4. Google OAuth (for `dissect`)

`cvdocs` needs a Google OAuth connection to read Docs for `dissect`. The local CLI uses the
simplest path: a one-time browser popup handles sign-in, and only you ever use this
connection.

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new
   project (any name).
2. **APIs & Services → Library** → search "Google Docs API" → **Enable**. (The Drive API
   is not needed — `cvdocs` never writes to Drive, only reads a Doc's content.)
3. **APIs & Services → OAuth consent screen** → User type **External** → fill the required
   fields → leave publishing status as **Testing** → under "Test users" add the Google
   account that can view the Doc(s) you'll dissect (this must be the account you'll
   actually sign in with in step 6).
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

### Usage

#### CLI

```
cvdocs auth login                                   # once
cvdocs dissect <google-doc-url>                     # populate output/blocks/

cvdocs blocks list                                  # see what's there
cvdocs blocks list --tag <tag>
cvdocs blocks list --query <text>                   # substring search over name/body
cvdocs blocks show <id>
cvdocs blocks delete <id>                           # permanent — no undo
cvdocs blocks preserve <id>                         # lock — exempt from `blocks clear`
cvdocs blocks unpreserve <id>                       # unlock
cvdocs blocks clear                                 # delete every non-preserved block

cvdocs generate --criteria "<what you want>"        # new block from scratch
cvdocs generate -f criteria.md                      # ...or read criteria from a file
cvdocs generate --criteria "<...>" --name <name>    # skip the naming call, use this name
cvdocs generate --criteria "<...>" --preserve       # lock the produced block on creation
cvdocs mutate <id> --criteria "<how to change it>"  # adapt an existing block
cvdocs mutate <id> -f criteria.md                   # ...or read criteria from a file
cvdocs mutate <id> --criteria "<...>" --name <name> # skip the naming call, use this name
cvdocs mutate <id> --criteria "<...>" --preserve    # lock the produced block on creation

cvdocs compose "<natural-language request>"         # writes output/results/<name>.md
cvdocs compose -f request.md                        # ...or read the request from a file
cvdocs compose "<request>" --dry-run                # show the plan, write nothing
cvdocs compose "<request>" --name <name>            # skip the naming call, use this name
cvdocs compose "<request>" --preserve               # lock the produced result on creation
cvdocs compose "<request>" --restrict-generate      # forbid brand-new blocks in the result
cvdocs compose "<request>" --restrict-mutate        # forbid edited variants; existing blocks used as-is
cvdocs compose "<request>" --from-blocks <id> --from-blocks <id>  # restrict candidates to exactly these blocks

cvdocs results list                                 # browse saved compose results
cvdocs results list --query <text>                  # substring search over name/content
cvdocs results show <result-id>                     # content + the request/plan behind it
cvdocs results delete <result-id>                   # permanent — no undo
cvdocs results preserve <result-id>                 # lock — exempt from `results clear`
cvdocs results unpreserve <result-id>               # unlock
cvdocs results clear                                # delete every non-preserved result
```

`-f`/`--criteria-file` (`generate`/`mutate`) and `-f`/`--request-file` (`compose`) read a
UTF-8 `.txt`/`.md` file instead of an inline argument. Pass either the inline form or the file.

Every LLM-taking command accepts `--model provider:model-id` to override the configured
default for that one call, e.g. `--model openrouter:z-ai/glm-5.3` or
`--model ollama:qwen3:4b`.

`--name` (`generate`/`mutate`/`compose`) skips that command's naming-model call and uses the
given name instead; `--preserve` marks the produced block/result as protected at creation
time — a protected entry is exempt from `blocks clear`/`results clear`.

`compose`'s `--restrict-generate` forbids the planner from producing any brand-new block;
`--restrict-mutate` forbids the planner from producing any edited variant of an existing block,
so every existing block in the result appears exactly as originally authored The two flags are
independent and may be combined, in which case the result is built entirely from existing
blocks used exactly as-is.

`compose`'s repeatable `--from-blocks <id>` restricts the planner's candidate pool to
exactly the designated blocks. Brand-new content is fully disabled for the call , while mutation
of a designated block stays available unless `--restrict-mutate` is also passed.

## Configuration

`config.yaml` (committed — no secrets live in it) is grouped into four sections:

- `llm.*` — which `provider:model-id` handles each task, plus provider connection settings.
  Mix and match freely — e.g. push the expensive planning work to a strong hosted model
  while keeping cheap tasks fully local and free.
- `path.*` — filesystem locations.
- `behavior.compose.*` — compose's own tuning knobs.
- `auth.*` — env names and paths to secrets and tokens, as well as auth redirect URI.

If some settings are applicable only to certain deployment type (CLI/hosted), there are
config fields for both. There's no need to change configs when changing deployment types,
since all variants live in the same file.

Secrets never live in `config.yaml` — only the *names* of the env vars that hold them do.
They live in a gitignored `.env` instead: `OPENROUTER_API_KEY` always; `GOOGLE_WEB_CLIENT_ID`,
`GOOGLE_WEB_CLIENT_SECRET`, and `CVDOCS_API_KEY` only if you're running the hosted deployment.
See `.env.example` for the full list.

## `input_prompts/constraints/`

Five files — `GENERATE_CONSTRAINTS.md`, `NAMING_CONSTRAINTS.md`, `MUTATE_CONSTRAINTS.md`,
`COMPOSE_CONSTRAINTS.md`, `KEYWORDS_CONSTRAINTS.md` — work like `CLAUDE.md`/`AGENTS.md`:
whatever you write in one is appended to that tool's system prompt on every call. Use them
for negative constraints ("don't do X") specific to your own use of the tool. A missing or
empty file is treated as no constraints, never an error.

## Tests

```
pytest
```

All LLM calls are mocked in the test suite (`tests/fakes.py`) — running the tests never
hits OpenRouter, Ollama, or the Google Docs API.
