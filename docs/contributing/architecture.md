# Architecture

How a request becomes a v3 API call. Install and client setup are in the [user docs](../README.md).

## Dispatch

`wagtail_mcp.dispatch` calls the project's v3 API in-process with `django.test.Client`. A tool names an `operation_id`; dispatch looks up the method and path in the OpenAPI document and sends a real `HttpRequest` through Django (auth, permissions, validation, actions, serialization). The MCP request's bearer token is forwarded, so the v3 API stays the authority for authorization.

Django's test client is used instead of django-ninja's `TestClient`. Ninja's client does not build a request Wagtail's page schemas can serialize (`html_url` needs a host). Notes for upstream are in [API feedback](api-feedback.md).

The v3 API must be mounted at `/api/v3/` (`MOUNT_PREFIX`). Schema paths already include that prefix. When `WAGTAILAPI_BASE_URL` is unset, `auth.current_host` copies the caller's `Host` into the in-process client so absolute URLs are not Django's `testserver`. Likewise, `auth.current_scheme` copies the caller's scheme into the client's `secure=` flag: with `SECURE_SSL_REDIRECT=True` a plain-http in-process call would be 301'd, and Django's client re-issues followed 301s as GET — silently turning every write into a no-op read (issue #5).

## HTTP transport

`wagtail_mcp.views` embeds the MCP SDK's ASGI Streamable HTTP transport in a sync Django view. Each POST builds an ASGI scope, runs a new stateless `StreamableHTTPSessionManager`, and copies the ASGI messages into an `HttpResponse`. Nothing is kept between requests, so WSGI and ASGI behave the same.

The view reaches the transport through `MCPServer._lowlevel_server`, a private SDK attribute. `mcp` is pinned to the version this was written against. An upgrade has to re-check that accessor and the per-request manager lifecycle.

The SDK's DNS-rebinding and Origin checks are off. Django's `ALLOWED_HOSTS` is the host gate, which is why `require_auth: False` is unsafe behind a lenient proxy. See [configuration](../configuration.md).

## Errors

`wagtail_mcp.errors` turns a v3 RFC 7807 problem document into one MCP tool string: title, status, detail, per-field `errors`, then a recovery hint for 401, 403, and 404. Missing keys are skipped.

## Tools

Modules under `wagtail_mcp.tools` register thin wrappers. Names match v3 `operation_id`s, except `api_call` and `api_schema`. List responses are trimmed; detail responses pass through. Snippet create/update take an opaque `data` dict because the shape comes from each model's `api_fields`. The user-facing list is the [tool reference](../tools.md).

## Admin agent

Optional extra `wagtail-mcp[agent]`. Opt-in by mounting: the URL namespace
`wagtail_mcp_agent` only exists once the project includes
`wagtail_mcp.agent.urls`, and every admin surface (menu item, chat page)
checks that condition per request. Until then the
page at `/admin/wagtail_mcp/agent/` renders setup instructions instead of the
chat. The page route itself is registered unconditionally — hook URLs are
frozen into the admin URLconf at import time, so availability is decided in
the view, not at registration. The steps are in [Admin agent](../admin-agent.md).

`build_registry()` copies each MCP tool function into django-ag-ui (name, description, parameter schema). A tool is marked destructive when its MCP annotations set `destructiveHint`, or when it is not read-only.

Tool calls mint a bearer `APIToken` named `wagtail-mcp-admin-agent` on the worker thread. pydantic-ai runs sync tools off the event loop, where ORM access raises `SynchronousOnlyOperation`, so the request factory only records the user and `Host`. The process caches the plaintext (Wagtail shows it only at creation) and deletes the row after a restart. Revocation is checked on the next call.

The chat bundle is `static/wagtail_mcp/js/agent.js`,
built from `static_src/agent/` with `npm run build:agent`. The standalone
chat page includes `templates/wagtail_mcp/admin/includes/agent_mount.html`,
which renders nothing when the endpoint namespace is absent. The bundle expects
`#wagtail-mcp-agent-root` with `data-endpoint` (posted to as-is) and
`data-csrf-token` (sent as `X-CSRFToken`).
