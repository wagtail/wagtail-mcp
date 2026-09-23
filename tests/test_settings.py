from wagtail_mcp.settings import get_agent_config, get_config


def test_defaults():
    assert get_config() == {
        "require_auth": True,
        "agent_model": "",
        "agent_api_key": "",
        "agent_base_url": "",
    }


def test_override(settings):
    settings.WAGTAIL_MCP = {"require_auth": False}
    assert get_config()["require_auth"] is False


def test_partial_override_keeps_defaults(settings):
    # A partial dict must not clobber unspecified defaults.
    settings.WAGTAIL_MCP = {"some_future_option": True}
    assert get_config()["require_auth"] is True


def test_agent_config_defaults_to_test_model(settings, monkeypatch):
    # Unset in settings: the agent runs on TestModel (empty model string).
    # Environment variables are not consulted — projects wire env vars into
    # WAGTAIL_MCP themselves (see demo/demo/settings/dev.py).
    monkeypatch.setenv("PROVIDER_API_KEY", "example-key")
    monkeypatch.setenv("PROVIDER_BASE_URL", "https://provider.example")
    settings.WAGTAIL_MCP = {}
    assert get_agent_config() == {"model": "", "api_key": "", "base_url": ""}


def test_agent_config_from_settings(settings, monkeypatch):
    # The project supplies the provider credentials directly in settings,
    # env vars are ignored.
    monkeypatch.setenv("PROVIDER_API_KEY", "example-key")
    monkeypatch.setenv("PROVIDER_BASE_URL", "https://provider.example")
    settings.WAGTAIL_MCP = {
        "agent_model": "openai:some-model",
        "agent_api_key": "settings-key",
        "agent_base_url": "https://provider.example/v1",
    }
    assert get_agent_config() == {
        "model": "openai:some-model",
        "api_key": "settings-key",
        "base_url": "https://provider.example/v1",
    }
