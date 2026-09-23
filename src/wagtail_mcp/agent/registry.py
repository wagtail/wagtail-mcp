"""Reflect the MCP server's tools into a django-ag-ui registry.

See docs/admin-agent.md.
"""

import functools

from contextvars import ContextVar

from django.http import HttpRequest
from django_ag_ui import ToolRegistry, ToolSpec
from django_pydantic_agent import AgentDeps
from mcp.server.mcpserver.tools import Tool as MCPTool

from wagtail_mcp import auth
from wagtail_mcp.agent.auth import get_api_token
from wagtail_mcp.server import get_server


# Bound per run by ``agent_deps_factory``, read when a tool actually runs.
_acting_user: ContextVar = ContextVar("wagtail_mcp_agent_acting_user", default=None)
_acting_host: ContextVar = ContextVar("wagtail_mcp_agent_acting_host", default=None)
_acting_scheme: ContextVar = ContextVar("wagtail_mcp_agent_acting_scheme", default=None)


def agent_deps_factory(request: HttpRequest):
    """Record the acting user, Host and scheme for this run.

    Called on the event loop, so it does not touch the ORM. The API token is
    minted inside the tool, on pydantic-ai's worker thread.
    """

    user = getattr(request, "user", None)
    _acting_user.set(user)
    try:
        host = request.get_host()
    except Exception:  # DisallowedHost and friends — mirrors mcp_endpoint.
        host = None
    _acting_host.set(host)
    _acting_scheme.set(request.scheme)
    return AgentDeps(user=user, ip_address=request.META.get("REMOTE_ADDR"))


def _is_destructive(tool: MCPTool) -> bool:
    """Map MCP annotations onto AG-UI's single destructive flag.

    ``destructiveHint`` wins; otherwise any non-read-only tool is a mutation
    (so a confirmation covers both ``pages_delete`` and ``pages_publish``).
    """
    annotations = tool.annotations
    if annotations is None:
        return False
    if annotations.destructive_hint:
        return True
    return annotations.read_only_hint is False


def _as_acting_user(fn):
    """Bind ``current_token`` / ``current_host`` / ``current_scheme`` around one tool call.

    Skips minting when a token is already bound, so a nested dispatch (the
    upload fallback) reuses it. The scheme is reset after the call so it
    cannot leak into unrelated dispatches on the same worker thread.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):

        if auth.current_token.get() is None:
            user = _acting_user.get()
            if user is not None:
                auth.current_token.set(get_api_token(user))
        scheme = _acting_scheme.get()
        scheme_token = None
        if scheme is not None and auth.current_scheme.get() is None:
            scheme_token = auth.current_scheme.set(scheme)
        try:
            host = _acting_host.get()
            if host is not None and auth.current_host.get() is None:
                auth.current_host.set(host)
            return fn(*args, **kwargs)
        finally:
            if scheme_token is not None:
                auth.current_scheme.reset(scheme_token)

    return wrapper


@functools.cache
def build_registry():
    """Build the AG-UI registry mirroring the MCP server's tools.

    Cached per process: the MCP server is itself a singleton, so reflecting
    it again would only rebuild the same schemas.
    """

    registry = ToolRegistry()
    for tool in get_server()._tool_manager.list_tools():
        registry.register(
            ToolSpec(
                name=tool.name,
                fn=_as_acting_user(tool.fn),
                description=tool.description or "",
                destructive=_is_destructive(tool),
            )
        )
    return registry


def reset_cache() -> None:
    """Forget the cached registry (tests)."""
    build_registry.cache_clear()


__all__ = ["agent_deps_factory", "build_registry", "reset_cache"]
