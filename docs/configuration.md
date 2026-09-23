# Configuration

## `WAGTAIL_MCP`

A dict, merged over defaults. Currently supported keys:

| Key | Default | Meaning |
|---|---|---|
| `require_auth` | `True` | Whether the MCP endpoint requires a valid bearer token. `False` allows anonymous tool calls for local tinkering only. |
| `agent_model` | `""` | pydantic-ai model for the [admin agent](admin-agent.md). Empty or `"test"` uses `TestModel` (no provider). `"openai:<model>"` uses the key and base URL below (any OpenAI-compatible endpoint). Any other string is passed through to pydantic-ai. |
| `agent_api_key` | `""` | Provider key for `agent_model`. |
| `agent_base_url` | `""` | Provider base URL for `agent_model`. |

```python
WAGTAIL_MCP = {
    "require_auth": True,
}
```

The admin agent is optional (`wagtail-mcp[agent]`) and needs an ASGI server.
See [admin agent](admin-agent.md).

**Warning — do not run with `require_auth: False` against anything but a
trusted localhost.** wagtail-mcp disables the MCP SDK's DNS-rebinding/Origin
checks because Django's `ALLOWED_HOSTS` already guards the view boundary; if
you disable `require_auth` *and* run behind a reverse proxy with a lenient
`ALLOWED_HOSTS`, neither the transport host check nor bearer auth is
enforcing identity, and the endpoint effectively lets anyone call mutating v3
tools. The demo site is only safe because it is explicitly localhost-only.

## Deployment

- **Works under WSGI and ASGI.** The MCP transport is ASGI-native, but the
  Django view embeds it per request with `asgiref.sync.async_to_sync`, so it
  behaves identically behind a WSGI or ASGI server. No extra processes, no
  separate sidecar.
- **Stateless.** The endpoint serves one POST = one JSON-RPC response. Non-POST
  methods return 405; there is no SSE/GET streaming and no server-side session.
  This is fine for OpenCode, Hermes and Claude-style clients that POST
  JSON-RPC.
- **No CSRF.** The endpoint is `csrf_exempt` — it's a bearer-authenticated,
  machine-to-machine endpoint, not a session-based browser form.

## Token security

- wagtail-mcp authenticates with a Wagtail `APIToken` (bearer). The token is
  resolved once at the MCP boundary and forwarded into the v3 API, which
  remains the single authority for authorization and permission checks.
- **Treat the token as a credential.** MCP client configs typically hold the
  bearer token in plaintext (e.g. `.opencode.json` or a Hermes profile); keep
  those files permission-restricted and out of version control. The demo writes
  its token to `demo/.demo_token` with mode `0600`.
- **Rotate** tokens by revoking them in Wagtail admin (Settings → API tokens)
  and issuing fresh ones; revocation takes effect immediately because the
  endpoint re-checks the token on every request.
- Use the least-privileged user you can for the tool surface you expose. For
  read-only work, a user with view-only permissions is enough and the v3 API
  enforces it.

## How absolute URLs in responses are resolved

The v3 API builds self-referential links (`meta.detail_url`, `meta.html_url`)
from the request's host or from `WAGTAILAPI_BASE_URL`:

- **Set `WAGTAILAPI_BASE_URL`** (e.g. `https://cms.example.com`) so these
  links are stable and correct regardless of how a client reaches the server.
  This is the recommended production setup.
- **When it is unset**, wagtail-mcp forwards the incoming MCP request's `Host`
  header into the in-process client, so links resolve to the caller's host
  rather than Django's hardcoded `testserver`. This is a fallback, not a
  substitute for setting the base URL — a site behind a proxy or with a
  non-canonical first-hop host can still see wrong links.

Other `WAGTAILAPI_*` settings the v3 API honors flow straight through (inherited
for free): `WAGTAILAPI_BASE_URL`, `WAGTAILAPI_LIMIT_MAX` (paginates the
per-request `limit` cap), `WAGTAILAPI_SEARCH_ENABLED` and
`WAGTAILAPI_RICH_TEXT_FORMAT`. Because wagtail-mcp dispatches in-process, any of
these that affect the request pipeline apply automatically.
