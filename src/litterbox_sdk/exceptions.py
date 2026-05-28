"""Typed errors for Litterbox interactions.

The hierarchy lets callers distinguish "I can't reach the service at
all" from "the service told me no" and lets them narrow on common HTTP
shapes (auth, not-found, conflict) without parsing status codes
themselves.
"""


class SandboxUnavailableError(RuntimeError):
    """Sandbox service is unreachable or fundamentally broken.

    Callers typically want to retry with backoff rather than surface to
    the user. Distinct from :class:`SandboxAPIError` because that
    family represents *the service responding with a refusal*, not a
    transport-level failure.
    """


class SandboxAPIError(RuntimeError):
    """Base for any error the sandbox service returned via HTTP."""


class SandboxAuthError(SandboxAPIError):
    """401/403 from the sandbox service. Token wrong, missing, or revoked."""


class SandboxNotFoundError(SandboxAPIError):
    """404 — the resource ID isn't known to the sandbox service.

    Common cause during host-attach paths: the host was already torn
    down by a sibling worker / housekeeping sweep.
    """


class SandboxConflictError(SandboxAPIError):
    """409 — the operation conflicts with the current state.

    e.g. provisioning a Linux user on a host that already has one with
    the same name.
    """


class SandboxResponseError(SandboxAPIError):
    """Everything else the service returned that the SDK doesn't classify."""
