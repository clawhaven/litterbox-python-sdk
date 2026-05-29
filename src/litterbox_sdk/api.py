"""Async HTTP client for Litterbox.

The service is the canonical owner of host provisioning, Tailscale
auth-key minting and device discovery, exe.dev VM lifecycle, and host
teardown. This SDK is a thin wrapper around its HTTP API; everything
that needs to happen *inside* a provisioned VM (SSH, file transfer,
command execution) is the caller's responsibility — the SDK hands back
the host record with ``ssh_host`` / ``ssh_port`` / ``known_hosts`` and
stops there.

Usage::

    from litterbox_sdk import SandboxAPI

    sandbox = SandboxAPI(
        base_url="https://sandbox.internal.ts.net",
        token="...",
        timeout=30.0,
    )
    try:
        host = await sandbox.create_host(image="ghcr.io/.../sandbox:abc123")
        # ... use host.ssh_host etc. with asyncssh ...
    finally:
        await sandbox.delete_host(host.id)
        await sandbox.aclose()

For env-backed config use :meth:`SandboxAPI.from_env`.
"""

import asyncio
import os
import uuid
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Self

import httpx

from .exceptions import (
    SandboxAuthError,
    SandboxConflictError,
    SandboxNotFoundError,
    SandboxResponseError,
)

# Explicit pool budget. The httpx defaults (100 / 20) are plenty for
# the SDK's traffic shape (a handful of provisioning calls per agent
# run), but keeping the values visible at the import site means a
# future bump in concurrency does not silently exhaust the pool.
_SANDBOX_HTTP_LIMITS = httpx.Limits(
    max_connections=20,
    max_keepalive_connections=5,
)


@dataclass(frozen=True)
class SandboxHost:
    """Snapshot of a provisioned host as returned by the service.

    The shape mirrors the Litterbox ``Host`` schema. The SSH
    connection bits (``ssh_host`` / ``ssh_port`` / ``known_hosts``) are
    everything a caller needs to open an SSH session — actually opening
    one is the caller's job; this SDK doesn't speak SSH.
    """

    id: str
    name: str
    status: str
    provider: str
    image: str
    ssh_host: str
    ssh_port: int
    known_hosts: str
    tailscale_device_id: str | None
    last_error: str
    created_at: str
    updated_at: str
    activated_at: str | None
    expires_at: str | None


_SANDBOX_HOST_FIELDS = {field.name for field in fields(SandboxHost)}


def _parse_sandbox_host(data: dict[str, Any]) -> SandboxHost:
    """Build a :class:`SandboxHost` picking only known fields.

    Defensive against the service adding new fields — those flow
    through harmlessly without breaking the SDK on the unsuspecting
    caller's side.
    """

    return SandboxHost(**{key: data[key] for key in _SANDBOX_HOST_FIELDS})


class SandboxAPI:
    """Async client for Litterbox.

    Construct one per process (or one per consuming subsystem) and
    reuse it. The internal ``httpx.AsyncClient`` is loop-aware: if the
    client gets used from a different event loop than the one it was
    created on (e.g. an ASGI request handler vs. a taskiq worker
    callback), it transparently rebinds to the running loop on next
    use. This is a known foot-gun with long-lived ``httpx.AsyncClient``
    instances; we handle it here so callers don't have to.

    Always call :meth:`aclose` during graceful shutdown.
    """

    def __init__(self, *, base_url: str, token: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        # The bound event loop is recorded the first time a client is
        # created. httpx clients are tied to the loop they were
        # instantiated on; reusing one across loops raises at request
        # time. Track the loop here so cross-loop reuse rebinds
        # instead of crashing.
        self._client_loop: asyncio.AbstractEventLoop | None = None
        # Concurrent first-callers can both observe ``self._client is
        # None`` and race to create two clients, leaking one. Serialize
        # the initialization path with a lazy-allocated lock.
        self._client_lock: asyncio.Lock | None = None

    @classmethod
    def from_env(cls, *, prefix: str = "SANDBOX_") -> Self:
        """Build from ``{prefix}SERVICE_URL`` / ``{prefix}SERVICE_TOKEN``
        / ``{prefix}SERVICE_TIMEOUT`` env vars.

        Convenience for callers that don't want to thread settings
        through their own config layer. The constructor stays the
        canonical entry point — this just reads the env once.
        """

        url = os.environ[f"{prefix}SERVICE_URL"]
        token = os.environ[f"{prefix}SERVICE_TOKEN"]
        timeout = float(os.environ.get(f"{prefix}SERVICE_TIMEOUT", "30"))
        return cls(base_url=url, token=token, timeout=timeout)

    # ------------------------------------------------------------------
    # Host lifecycle
    # ------------------------------------------------------------------

    async def create_host(
        self,
        *,
        env: dict[str, str] | None = None,
        expires_at: datetime | None = None,
        idempotency_key: str | None = None,
        image: str | None = None,
    ) -> SandboxHost:
        """Provision a new host.

        Returns once the service has recorded the request; the host may
        still be in ``provisioning`` state. Poll :meth:`get_host` to
        wait for it to reach ``active``. ``idempotency_key`` is sent as
        the service's ``Idempotency-Key`` header.
        """

        payload: dict[str, Any] = {}
        if env is not None:
            payload["env"] = env
        if expires_at is not None:
            payload["expires_at"] = expires_at.isoformat()
        if image is not None:
            payload["image"] = image

        headers: dict[str, str] = {}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        data = await self._request("POST", "/hosts", json=payload, headers=headers)
        assert isinstance(data, dict)
        return _parse_sandbox_host(data)

    async def get_host(self, host_id: uuid.UUID | str) -> SandboxHost:
        data = await self._request("GET", f"/hosts/{host_id}")
        assert isinstance(data, dict)
        return _parse_sandbox_host(data)

    async def attach(self, host_id: uuid.UUID | str) -> SandboxHost:
        """Alias for :meth:`get_host` that reads better at call sites
        coming back to a host they provisioned in an earlier process.

        Same wire call; the rename only exists so a restart-resumption
        path doesn't have to start with ``get_host`` (which would read
        like "go discover a host" when the intent is "reattach to one
        I already know about").
        """

        return await self.get_host(host_id)

    async def list_hosts(self) -> list[SandboxHost]:
        data = await self._request("GET", "/hosts")
        assert isinstance(data, list)
        return [_parse_sandbox_host(item) for item in data]

    async def delete_host(self, host_id: uuid.UUID | str) -> None:
        await self._request("DELETE", f"/hosts/{host_id}")

    async def aclose(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None
        self._client_loop = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        client = await self._get_client()
        request_headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if headers is not None:
            request_headers.update(headers)

        try:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers=request_headers,
                timeout=self.timeout,
            )
        except httpx.RequestError as exc:
            raise SandboxResponseError(f"Sandbox service transport failed: {exc}") from exc

        if response.status_code == 204:
            return {}

        try:
            json_response = response.json()
        except ValueError as exc:
            raise SandboxResponseError("Sandbox service returned non-JSON output") from exc

        if response.status_code in {401, 403}:
            raise SandboxAuthError(json_response.get("detail", "auth failed"))

        if response.status_code == 404:
            raise SandboxNotFoundError(json_response.get("detail", "not found"))

        if response.status_code == 409:
            raise SandboxConflictError(json_response.get("detail", "conflict"))

        if response.status_code >= 400:
            raise SandboxResponseError(json_response.get("detail", "error"))
        return json_response

    async def _get_client(self) -> httpx.AsyncClient:
        running_loop = asyncio.get_running_loop()
        # Fast-path: client exists and is bound to the current loop.
        if self._client is not None and self._client_loop is running_loop:
            return self._client
        # Slow-path: either no client yet, or the client is bound to a
        # stale loop (e.g. fixture teardown). Serialize through the
        # lock.
        if self._client_lock is None:
            self._client_lock = asyncio.Lock()
        async with self._client_lock:
            # Re-check under the lock; another coroutine may have raced
            # ahead.
            if self._client is not None and self._client_loop is running_loop:
                return self._client
            if self._client is not None:
                # Stale-loop client: closing on its own loop is unsafe,
                # so drop the reference and rely on GC. httpx will emit
                # an "unclosed client" warning, which is the correct
                # signal that the process-level lifecycle hook
                # (ASGI lifespan / taskiq WORKER_SHUTDOWN) didn't run
                # on the previous loop.
                self._client = None
                self._client_loop = None
            self._client = httpx.AsyncClient(limits=_SANDBOX_HTTP_LIMITS)
            self._client_loop = running_loop
            return self._client
