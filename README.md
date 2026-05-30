# litterbox-python-sdk

Async Python client for the [Litterbox] host API.

The SDK provisions sandbox VMs, reads host state, deletes hosts, and
returns the SSH connection details a caller needs. It speaks HTTP only:
SSH sessions, file transfer, command execution, and retry orchestration
belong in the caller.

## Install

```bash
pip install litterbox-python-sdk
uv add litterbox-python-sdk
```

## Usage

```python
from litterbox_sdk import SandboxAPI

sandbox = SandboxAPI(
    base_url="https://sandbox.internal.ts.net",
    token="...",
)

try:
    host = await sandbox.create_host(
        image="ghcr.io/litterbox/sandbox:abc123",
        env={"FOO": "bar"},
        idempotency_key="agent-run-42",
    )
    # Use host.ssh_host, host.ssh_port, and host.known_hosts with
    # asyncssh or another SSH client.
finally:
    await sandbox.delete_host(host.id)
    await sandbox.aclose()
```

`create_host` blocks until the host is `active` — typically ~10–30s, up to a
few minutes worst case. The SDK's default `timeout` (300s) covers this. Pass
an `idempotency_key` for retry safety: a retry with the same key after a
successful provision returns the original host instead of creating a duplicate.

`SandboxAPI.from_env(prefix="SANDBOX_")` reads
`SANDBOX_SERVICE_URL`, `SANDBOX_SERVICE_TOKEN`, and optional
`SANDBOX_SERVICE_TIMEOUT`.

## Contract

Public exports live in `litterbox_sdk`:

- `SandboxAPI`
- `SandboxHost`
- `SandboxAPIError` and typed subclasses for auth, not found, conflict,
  unavailable, and unclassified response errors

Supported host operations:

- `create_host`
- `get_host`
- `attach`
- `list_hosts`
- `delete_host`
- `aclose`

`create_host` supports the service's optional `image`, `env`, `expires_at`,
and `Idempotency-Key` inputs.

The SDK does not mint Tailscale auth keys, manage ACLs, establish SSH,
provision Linux users, transfer files, or run remote commands.

## Development

```bash
uv sync
uv run ruff check
uv run ruff format --check
uv run pyright
uv run pytest
```

Tests use `respx` to fake the Litterbox HTTP API. They do not need a
real network, VM provider, or Litterbox service.

[Litterbox]: https://github.com/clawhaven/litterbox
