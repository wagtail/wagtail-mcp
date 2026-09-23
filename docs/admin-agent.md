# Admin agent

Experimental chat inside the Wagtail admin. It exposes the same MCP tools as
the `/mcp/` endpoint, called in-process, to a browser session.

## Install

Install the extra (`pip install wagtail-mcp[agent]`, or `uv sync --extra agent`)
and serve the site with an ASGI server. Under WSGI the response is correct but
buffered, so the stream does not arrive incrementally. The demo uses
`just runserver-asgi` (uvicorn).

## Mount the endpoint

The agent is opt-in: until the endpoint is mounted, none of the agent UI
appears in the admin, and `/admin/wagtail_mcp/agent/` renders setup
instructions instead of the chat.

| URL | Mounted by | Role |
| --- | --- | --- |
| `/admin/wagtail_mcp/agent/` | `register_admin_urls` | HTML page (setup instructions until the endpoint below is mounted). Wagtail's admin gate applies. |
| `/admin/wagtail_mcp/agent/api/` | project URLconf: `include("wagtail_mcp.agent.urls")` | AG-UI run endpoint and tool catalog. |

Mount the include yourself, **before** the admin URLconf, or the admin
catch-all swallows the path:

```python
urlpatterns = [
    path("admin/wagtail_mcp/agent/api/", include("wagtail_mcp.agent.urls")),
    path("admin/", include(wagtailadmin_urls)),
]
```

The endpoint answers JSON (401 anonymous, 403 otherwise), not an HTML login
redirect, so a failed run does not replace the stream with a login page.

## Authentication

Two credentials:

- The **session** authenticates the browser. CSRF stays on.
- An **`APIToken`** authenticates tool dispatch. The v3 API only accepts a
  bearer token; a session cookie never reaches it.

The token is named `wagtail-mcp-admin-agent` and listed under Settings → API
tokens. Revoking it stops the agent on the next tool call.

## Model

`WAGTAIL_MCP` keys are in [configuration](configuration.md). An empty or
`"test"` model uses pydantic-ai's `TestModel`, which calls the tools without
a provider. `openai:<model>` with a key or base URL uses that
OpenAI-compatible endpoint. Any other string is left
for pydantic-ai to resolve.

The demo reads `WAGTAIL_MCP_AGENT_MODEL`, `WAGTAIL_MCP_AGENT_API_KEY` and
`WAGTAIL_MCP_AGENT_BASE_URL` from the environment into `WAGTAIL_MCP` (see
`demo/demo/settings/dev.py`).

How the endpoint is wired, how the token is cached, and how the frontend
bundle is built: [architecture](contributing/architecture.md).
