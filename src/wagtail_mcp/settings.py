from django.conf import settings


DEFAULTS = {
    "require_auth": True,
    # Reject POST bodies larger than this many bytes with 413. ``None`` = no limit.
    "max_request_bytes": None,
    # Allow at most ``rate_limit_requests`` requests per ``rate_limit_window``
    # seconds for each token (429 beyond that). ``None`` = no limit.
    "rate_limit_requests": None,
    "rate_limit_window": 60,
    # See docs/admin-agent.md for model and provider configuration.
    "agent_model": "",
    "agent_api_key": "",
    "agent_base_url": "",
}


def get_config() -> dict:
    """Return the wagtail_mcp settings, merging project overrides onto defaults.

    A project may provide a partial ``WAGTAIL_MCP`` dict; unspecified options
    fall back to ``DEFAULTS``.
    """
    return {**DEFAULTS, **getattr(settings, "WAGTAIL_MCP", {})}


def get_agent_config() -> dict:
    """Return the admin agent's model config."""
    config = get_config()
    return {
        "model": config["agent_model"],
        "api_key": config["agent_api_key"],
        "base_url": config["agent_base_url"],
    }
