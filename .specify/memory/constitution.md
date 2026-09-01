<!--
Sync Impact Report
- Version change: 1.0.0 → 1.1.0
- Modified principles: none renamed; minor typo/wording fixes in I, IV, V (non-semantic)
- Added principles: VI. Minimal, Behavior-Only Comments
- Added sections: none
- Removed sections: none (Development Workflow's now-redundant comment-style sentence
  removed, superseded by Principle VI)
- Follow-up TODOs: none
-->

# cvdocs Constitution

## Core Principles

### I. Protocol-Based Pluggability
Every cross-cutting concern that has more than one real or foreseeable implementation MUST
be expressed as a small `Protocol` with a single dispatch chokepoint that selects a concrete
implementation from a config value. Call sites depend on the Protocol, never on a concrete
implementation directly. A new implementation MUST satisfy the existing Protocol with zero
changes to its callers; if it can't, the Protocol is wrong and must be fixed, not worked
around at the call site.

### II. No Speculative Abstraction, Nothing Silently Dropped
Do not build for a future that isn't being built yet until that future is the actual task at
hand. Every deliberately-deferred concern MUST be named explicitly (e.g. a "Known gaps" note)
rather than silently omitted — future work should never have to rediscover a gap that was
already known. Prefer direct, breaking changes over backwards-compatibility shims or
renamed-symbol aliases when a rename/move happens; this codebase does not carry dead
compatibility layers.

### III. Live Verification Over the Real Stack (NON-NEGOTIABLE)
A feature is not complete when its unit tests pass — it is complete when it has been run
against the real stack it will actually use (real OpenRouter/Ollama calls, the real block
library, real generated/mutated files or DB rows) and the actual output inspected. Unit tests
with fakes (`tests/fakes.py`) catch logic bugs; only a live run catches real-model behavior
(hallucination, retries, non-determinism, prompt drift) that a scripted fake cannot
reproduce. Live-verification artifacts created during this process MUST be cleaned up before
the work is reported done, unless the user asks otherwise.

### IV. Decoupled, Independently Testable Core Logic
Core decision logic (naming/dedup decisions, retrieval scoring, field parsing) MUST take
plain in-memory data and injected callables — never reach into `Settings`, file I/O, or a
specific storage backend directly. A module that needs Settings/IO to make a decision it
could otherwise make from data alone is a design smell to fix, not a convenience to keep.

### V. Single Source of Truth for Configuration
`config.yaml` is the source of truth for every setting. Environment variables are reserved
narrowly for two things only: secrets (e.g. `OPENROUTER_API_KEY`) and genuine
deployment-environment facts that a checked-in file cannot express (e.g.
`CVDOCS_STORAGE_BACKEND` — "am I running in a container"). Environment variables MUST NOT
become a general override mechanism for ordinary settings; each new env-sourced value needs
its own explicit justification, documented at its point of use.

### VI. Minimal, Behavior-Only Comments
Default to no comments; well-named identifiers carry the *what*. When a comment is genuinely
needed, it MUST be a few words to a single short line — never a multi-line block. A change
MUST NOT be accompanied by comments narrating that a change was made, what it replaced, or
why it was edited right now; a comment describes the code's current behavior, not its history
— that belongs in the commit message or session summary, not the source. Comments MUST
describe logic/behavior only and MUST NOT include illustrative examples (no "e.g. ..."); an
example belongs in a test, not inline in a comment.

## Technology & Testing Constraints

Python 3.11+, Typer + Rich for the CLI, pydantic `BaseModel`s for all configuration. Prefer
the standard library over a new dependency (e.g. `sqlite3` over an ORM) unless the problem
genuinely outgrows what stdlib can do proportionately. The test suite (`pytest`) MUST NOT
make real network/API calls — every LLM call is mocked via `tests/fakes.py`'s
`FakeLLMClient`/`FakeBlockStorage`/`FakeResultStorage`; filesystem-backed tests use
`pytest`'s real `tmp_path`, never the project's own `output/` directories. A new pluggable
backend MUST ship with its own test coverage before being considered done, and MUST be
exercised by at least one live run (Principle III) prior to being reported complete.

## Development Workflow

Changes affecting more than a couple of files, or introducing a new architectural pattern,
go through a plan first (see this project's use of Claude Code's plan mode) — implementation
starts only once the plan is scoped and agreed. Prefer a scoped, mechanical refactor now over
leaving a known inconsistency for "later" when the cost of doing it now and later is roughly
the same.

## Governance

This constitution supersedes ad hoc practice for anything it covers. Amendments happen via
this same document, through the constitution-update workflow — not by silent drift in
unrelated commits. Any deviation from a principle (e.g. skipping live verification, adding an
env-var override outside Principle V's narrow carve-out) MUST be justified explicitly in the
PR/commit description or session summary at the time it happens, not retrofitted later.
Complexity (a new dependency, a new abstraction layer, a new config axis) must be justified
against Principle II before it's added.

**Version**: 1.1.0 | **Ratified**: 2026-09-01 | **Last Amended**: 2026-09-01
