# AGENTS.md

Guide for AI agents working in `litterbox-python-sdk`.

## What This Project Is

`litterbox-python-sdk` is the async Python SDK for Litterbox's HTTP host
API. It is a small client library, not the Litterbox service and not an SSH
execution layer.

The package name is `litterbox-python-sdk`; the import package is
`litterbox_sdk`. Public API names still use `Sandbox*` because the Litterbox
domain object is a sandbox host.

## Boundaries

- Keep this repo focused on HTTP client behavior, typed records, and typed
  exceptions.
- Do not add SSH session management, file transfer, command execution,
  Tailscale management, VM provider logic, or service-side lifecycle behavior.
- Do not introduce compatibility shims for old repo names or stale payload
  contracts unless explicitly requested.
- Prefer explicit Litterbox wire contracts over broad defensive parsing.
- Keep dependencies light; justify any new runtime dependency before adding it.

## Layout

```text
src/litterbox_sdk/
  api.py          # SandboxAPI, records, parsers, HTTP request handling
  exceptions.py   # SDK exception hierarchy
  __init__.py     # Public exports
tests/
  test_api.py     # respx-backed SDK contract tests
```

## Development Commands

```bash
uv sync
uv run ruff check
uv run ruff format --check
uv run pyright
uv run pytest
```

Run the full set when changing Python behavior. For documentation-only edits,
at least search for stale names with `rg` and state that tests were not run.

## Working Rules

- Read this file, `pyproject.toml`, and the relevant source/tests before
  editing.
- Follow the repo's Python 3.11+ typing style and keep public APIs typed.
- Match the existing async `httpx` style and strict typing.
- Add focused tests for behavior changes.
- Keep docs concise and repo-specific. Avoid references to downstream
  consumers unless the user asks for them.
- Preserve user changes in the worktree; do not clean or rewrite unrelated
  files.
