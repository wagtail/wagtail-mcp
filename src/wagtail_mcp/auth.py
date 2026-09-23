from contextvars import ContextVar

from django.http import HttpRequest
from wagtail.models import APIToken


# Request-scoped bearer token forwarded to in-process dispatch.
current_token: ContextVar[str | None] = ContextVar("wagtail_mcp_token", default=None)

# Caller ``Host`` for the in-process client. See docs/contributing/architecture.md.
current_host: ContextVar[str | None] = ContextVar("wagtail_mcp_host", default=None)

# Caller scheme (``"http"``/``"https"``) for the in-process client.
# See docs/contributing/architecture.md.
current_scheme: ContextVar[str | None] = ContextVar("wagtail_mcp_scheme", default=None)


def resolve_bearer(request: HttpRequest) -> str | None:
    """Resolve ``Authorization: Bearer <token>`` to a valid APIToken's plaintext.

    Returns the plaintext token string if it matches a live, un-revoked APIToken
    whose user is active; otherwise ``None``. Permission checks are deliberately
    NOT performed here — the v3 API remains the single point of truth for
    authorization (the matched user is derived from the token and v3 enforces
    permissions on the operations themselves).
    """
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    if not APIToken.validate_token_format(token):
        return None
    try:
        api_token = APIToken.objects.select_related("user").get(
            key_hash__in=APIToken.candidate_key_hashes(token), revoked_at__isnull=True
        )
    except APIToken.DoesNotExist:
        return None
    return token if api_token.user.is_active else None
