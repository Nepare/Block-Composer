# cvdocs — working notes for Claude

A configurable block library and composer, sourced from Google Docs (see `README.md` for the
full user-facing description, setup, and CLI usage — don't duplicate that here).

## Development process (read this before writing any code)

This project is **spec-driven**. Every non-trivial feature goes through the Spec Kit pipeline
in `.claude/skills/speckit-*` / `.specify/`, in this order:

1. `speckit-specify` — turns a feature description into `specs/NNN-name/spec.md` (user
   scenarios, functional requirements, success criteria — no implementation detail).
2. `speckit-clarify` — only if the spec has open `[NEEDS CLARIFICATION]` markers.
3. `speckit-plan` — turns the spec into `specs/NNN-name/plan.md` (+ `research.md`,
   `data-model.md`, `contracts/`, `quickstart.md`) — the actual technical design.
4. `speckit-tasks` — turns the plan into `specs/NNN-name/tasks.md`, a dependency-ordered task
   list.
5. `speckit-implement` — executes the tasks. Always goes with the argument "The main agent is the orchestrator, the tasks are done by subagents. Use parallel deployment of subagents where possible. Remind subagents that they are not
orchestrators themselves and need to do the task by themselves. Don't forget to check completed tasks."

Past features are the reference examples for tone and structure —
read one before writing a new spec. **Do not jump straight to editing source files** for
anything beyond a trivial, obviously-scoped fix; if a request sounds like a feature rather than
a one-line correction, start at `speckit-specify`, not at `Edit`.

Feature numbering is sequential (`.specify/init-options.json`); there is no per-feature git
branch convention here — everything so far has shipped directly on `main`.

The commit naming convention is <feat/fix/refactor>: brief description (no more than 2 sentences). 

`.specify/memory/constitution.md` is the project's binding constitution (Protocol-based
pluggability, no speculative abstraction, live verification over the real stack, decoupled
core logic, config.yaml as the single source of truth, minimal behavior-only comments). Read it
once per session rather than re-deriving these rules from the diff each time.

## Ask before deciding, not after building

When a feature has more than one reasonable technical shape (transport mechanism, where state
lives, how wide a slice to build), surface the real options and ask — don't silently pick one
and present finished code. Every past feature's spec/plan reflects explicit decisions, several
made by asking the user directly rather than assuming. Treat "let's build X" as "let's *design*
X, then build it," not as license to skip straight to implementation. Ask as many questions as reasonably viable.

## Architecture map

`src/` is grouped by domain — `cli.py` is the only flat file left at root, everything else
lives under `core/`, `tools/`, `models/`, `web/`, `storage/`, `auth/`, `llm/`, `parsing/` 
packages. `tests/` mirrors this 1:1 (plus a `unit/` bucket for
`core/`'s own tests) — `tests/conftest.py`/`tests/fakes.py`/`tests/fixtures/`/`test_cli.py`
stay at `tests/` root, shared across every category.

- `src/cli.py` — Typer CLI, the primary interface today (`cvdocs <command>`).
- `src/web/` — FastAPI hosted-deployment service (`webapp.py`) plus its background-job/SSE
  scaffold (`web_jobs.py`, `Job`/`start_job`/`sse_events` — generic, no cancellation support).
  Exposes the hosted Google OAuth routes (`/auth/google/login`, `/auth/google/callback`) and
  `generate`/`mutate`'s HTTP surface (`POST /generate/start`, `GET /generate/stream/{job_id}`,
  same for `mutate`). `compose`'s own HTTP endpoints and `dissect`/library HTTP are not built
  yet. No frontend code exists yet.
- `src/tools/` — the core tools: `compose.py`, `generate.py`, `mutate.py`, `dissect.py`,
  `retrieval.py`, `docs_api.py`. `compose.py`'s `run_compose()` takes an injectable
  `on_progress` (`ProgressSink`, see `core/progress.py`) and `cancel_check` callable — built
  for exactly this kind of long-running, observable, cancellable operation, CLI or HTTP.
- `src/models/` — dataclasses/data shape: `blocks.py` (`Block`), `block_fields.py` (parses a
  block's Markdown body into structured fields), `templates.py` (`templates.yaml`'s schema).
- `src/core/` — cross-cutting, no single owning domain: `config.py` (`Settings`, see below),
  `errors.py` (the `CvdocsError` hierarchy), `constraints.py`, `progress.py`
  (`ProgressEvent`/`ProgressSink`), `text_input.py`, `naming.py` (shared dedup/slug logic used
  by every block-writing path).
- `src/storage/` — `Protocol`-based pluggable backends (`base.py` defines `BlockStorage` /
  `ResultStorage` / `CredentialsStorage`; `filesystem.py` and `sqlite.py` implement them;
  `router.py` dispatches by `Settings.path.storage.backend`). Hosted/Docker deployments use
  `sqlite`; local CLI use defaults to `filesystem`.
- `src/auth/` — two OAuth flows behind one interface: `installed_app.py` (local CLI, browser
  popup) and `web.py` (`WebAuthProvider`, hosted deployment, redirect-based); `router.py`
  dispatches between them.
- `src/llm/` — provider-agnostic LLM client (`router.py` dispatches `provider:model` specs to
  `providers/openrouter.py` / `providers/ollama.py`), plus `logging_client.py` for
  diagnostic `ProgressEvent`s and `prompts.py` for the actual prompt text.
- `src/core/config.py` — `Settings` (pydantic), loaded from `config.yaml` + `.env`/env vars
  (`load_settings()`), grouped into four sections: `llm` (providers/models), `path`
  (filesystem locations, storage backend, constraint file paths), `behavior` (compose's tuning
  knobs), `auth` (Google OAuth, hosted-deployment API key). Env vars are reserved for secrets
  and genuine deployment-environment facts only (Constitution Principle V) — not a general
  override mechanism.
- `tests/fakes.py` — `FakeLLMClient`, `FakeBlockStorage`, `FakeResultStorage`; the test suite
  never makes a real network call. `tests/conftest.py`'s `settings`/`fake_router`/
  `fake_storage` fixtures are the standard way to wire fakes into a test.

## Design approach

- Don't write expansive comments explaining the change diffs, don't write docstrings with the same purpose. Non-trivial behavior should be explained in 1 comment line at max.
- Never use concrete examples in comments, README or documentation. Keep the arguments and results abstract if you really need to include them into non-code natural language explanations.
- When writing files of a similar domain, if those files are related, try placing them in a folder — e.g. storage backends in `storage/`, core tools in `tools/`, dataclasses in `models/`, HTTP exposure in `web/`, cross-cutting utilities in `core/`, `.md` input prompts in `input_prompts/`. Try keeping it the same way.

## Testing & verification

- `pytest` runs fully offline (mocked LLM calls, `tmp_path`-backed storage — never the repo's
  own `output/` directory).
- Constitution Principle III (non-negotiable): a feature isn't done when unit tests pass — it
  needs at least one live run against the real stack it will use, with cleanup of any
  live-verification artifacts before reporting done.
