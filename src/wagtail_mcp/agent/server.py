"""AG-UI endpoint for the Wagtail admin agent. See docs/admin-agent.md."""

from django.http import HttpRequest
from django_ag_ui import AGUIServer, ToolRegistry

from wagtail_mcp.agent.registry import agent_deps_factory, build_registry
from wagtail_mcp.settings import get_agent_config


def staff_required(request: HttpRequest) -> bool:
    """Authenticated staff user. The view turns a false result into a 403."""
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_staff)


def _model_for_settings():
    """Resolve the pydantic-ai model from settings.

    An empty or ``"test"`` model is pydantic-ai's ``TestModel`` (no network).
    ``openai:<name>`` with a key or base URL builds an ``OpenAIChatModel`` on
    that OpenAI-compatible provider. Anything else is returned as a string
    for pydantic-ai to infer.
    """

    config = get_agent_config()
    model = config["model"]
    if not model or model == "test":
        from pydantic_ai.models.test import TestModel

        return TestModel()
    if model.startswith("openai:") and (config["api_key"] or config["base_url"]):
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIChatModel(
            model_name=model.removeprefix("openai:"),
            provider=OpenAIProvider(
                api_key=config["api_key"] or None,
                base_url=config["base_url"] or None,
            ),
        )
    return model


class WagtailMCPAgentServer(AGUIServer):
    """Staff-only, CSRF-enforced AG-UI server over the MCP tool registry.

    Keyword arguments pass through to ``AGUIServer`` (stores, throttle, …).
    """

    def __init__(self, registry: ToolRegistry | None = None, **kwargs) -> None:
        model = kwargs.pop("model", None)
        if model is None:
            model = _model_for_settings()
        super().__init__(
            registry if registry is not None else build_registry(),
            model=model,
            require_authenticated=True,
            authorize=staff_required,
            csrf_exempt=False,
            deps_factory=agent_deps_factory,
            namespace="wagtail_mcp_agent",
            **kwargs,
        )


__all__ = ["WagtailMCPAgentServer", "staff_required"]
