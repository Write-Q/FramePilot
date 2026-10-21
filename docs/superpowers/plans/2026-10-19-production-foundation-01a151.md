# Production Foundation Implementation Plan

> **For agentic workers:** Use executing-plans to implement this plan task-by-task in this session. Do not delegate. Steps use checkbox syntax for tracking.

**Goal:** Deliver versioned model configuration and confirmed-script-to-editable-storyboard APIs without paid calls.

**Architecture:** Add a focused `app/production` package. Reuse existing immutable domain tables and legacy script identities; add model profile revisions and storyboard confirmation tables with a frozen migration. Expose a separate router, leaving existing writer internals intact.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy Core, PostgreSQL, Alembic, pytest.

## Task 1: Contracts

Files: create `app/production/contracts.py`, `app/production/__init__.py`, `tests/test_production_contracts.py`.

- [x] Write tests constructing `ModelConfig` and `StoryboardContent`. Reject credentials in URLs, arbitrary API key fields, secret-like extension parameters, duplicate shot keys, nonexistent scene keys and invalid durations. Add size bounds to contracts. Check that text/image/video/review/asr/tts are independently selectable.
- [x] Run `.\.venv\Scripts\python.exe -m pytest tests/test_production_contracts.py -q -p no:cacheprovider` and observe missing-contract failures.
- [x] Define strict, versioned schemas with `ConfigDict(extra='forbid')`. Keep opaque capability claims separate from verified execution support. Use integer milliseconds for shot duration and explicit stable shot keys.
- [x] Rerun contracts tests and record results.

Contract example:

```python
config = ModelConfig(name='分镜规划', purpose='text', adapter='openai_chat',
    base_url='https://example.test/v1', model='model-a', api_key_env='FP_PLANNER_KEY')
assert config.model_dump()['api_key_env'] == 'FP_PLANNER_KEY'
```

## Task 2: Persistence and configuration API

Files: create `app/production/schema.py`, `app/production/store.py`, `app/production/api.py`, `migrations/versions/0005_production_foundation.py`, `tests/test_production.py`; minimally modify `app/models.py`, `app/main.py`.

- [x] Add PostgreSQL/API tests for create/list/update/read a model profile. Update uses expected revision, inserts immutable revision 2, and preserves revision 1. Reject stale update and malformed config. Register metadata and frozen migration, refusing downgrade when new data exists.
- [x] Implement profile persistence with short transactions and `SELECT FOR UPDATE`, missing=404 and conflict=409. Store only an environment variable name for credentials. List and read contain configuration metadata, never resolved environment values. Do not add automatic startup migrations.
- [x] Expose `/api/production/model-profiles`, `/model-profiles/{id}` and `/model-profiles/{id}/versions/{version}`; `/adapters` advertises reserved adapters with `executable=false` until actual integration exists. Validate bound configuration identity, version and purpose before saving storyboards.
- [x] Run targeted PostgreSQL tests in isolated random databases, then include them in `scripts.test_local`. Record actual failures and fix before moving on.

## Task 3: Script handoff, storyboard revisions and confirmation

Files: extend new contracts/store/api and `tests/test_production.py` only.

- [x] Test confirmed old-script handoff, manual scene/shot inputs, exact source quotes, versioned profile bindings, rejection of unconfirmed/stale scripts and foreign scene/profile references.
- [x] Under project row lock, read existing script-version mapping, create breakdown/scenes/storyboard/shots transactionally. Persist only after the full content validates. Revision uses the same breakdown and sequential version allocation; preserve stable shot keys in JSON content and use new database IDs for each version's rows.
- [x] Test edit with expected current version, old-version reads, confirmation idempotency and new-version unconfirmed state. Validate current source again before confirmation and expose source-current status on reads. A later upstream change must not mutate saved history.
- [x] Expose project-scoped storyboard create/list/read/revise/confirm endpoints, and test them through the application's installed router.

## Task 4: Verification and handoff

Files: create `docs/production-foundation.md`, update this plan and `docs/devlog/2026-10-19-production-foundation-01a151.md`.

- [x] Run focused contracts and integration tests, then the full existing suite. No external model calls. Final run includes configured browser dependencies: 157 passed, 0 skipped.
- [x] Verify frozen migration by applying Alembic through PostgreSQL fixtures and exercising registered metadata; inspect `git diff --check` and scope. Nonempty downgrade protection tested. Do not migrate business DB, commit unrelated files or clean worktrees.
- [x] Document complete API request examples, explicit upgrade command, env-secret semantics and limitations. Update devlog with evidence, modified files, deferred provider/UI/worker/media tasks and next executable steps.

## Execution result

First slice complete: 26 contract tests, 11 new API/PostgreSQL tests; full 157 passed / 0 skipped / one existing third-party deprecation warning. Read-only review found an unknown-key validation echo, reproduced by a failing test and fixed with schema-field whitelisting. The reviewed writer baseline was separately committed as 5534950 at the user's request. Production changes remain uncommitted in the shared workspace; no production DB migration, paid calls, push or cleanup occurred.

Follow-on stages remain separate: provider execution and paid-call accounting; AI storyboard planning using the researched rules; asset/media handling; durable video jobs; actual video review; versioned editing and FFmpeg rendering; UI. Supplier details are still pending and do not affect this slice's completion.
