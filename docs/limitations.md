# Limitations

This page documents current wagtail-mcp limitations — the scope it deliberately
does not cover and the coupling that comes with reusing the Wagtail v3 API.

## Transport

One POST is one JSON-RPC response. There is no SSE stream, no server-side
session, and no server push, so clients that need those are unsupported.
Non-POST methods return 405 before any auth check. How the view embeds the
MCP SDK, and why `mcp` is pinned, is in
[architecture](contributing/architecture.md). Absolute URLs in responses are
covered in [configuration](configuration.md). The incoming request's scheme
(`request.scheme`, which honours `SECURE_PROXY_SSL_HEADER`) is replicated
in-process too, so `SECURE_SSL_REDIRECT` does not 301 internal calls (a
followed 301 re-issues the request as GET, silently turning every write into
a no-op read).

## Authentication

- **No OAuth (yet).** Authentication uses Wagtail `APIToken` bearer tokens.
  Planned roadmap: OAuth 2.1 for the MCP HTTP transport (e.g. via
  `django-oauth-toolkit` or the MCP SDK's auth-provider hooks). Because both
  the token path and an OAuth path resolve to the same Wagtail user model and
  only change the identity resolution at the MCP boundary, the 60 tools are
  agnostic to the choice — the migration should be transparent to tool callers.
- **Plaintext token in client configs.** MCP client configs typically store the
  bearer token in plaintext; keep them permission-restricted and out of version
  control, and rotate tokens (revocation applies immediately). See
  [configuration](configuration.md).

## Coverage gaps

- **No workflow/moderation endpoints.** The v3 API does not expose submitting,
  approving or rejecting workflow tasks yet, so there are no corresponding
  tools.
- **No tags write on images/documents.** The v3 image/document write schemas
  expose no tags input (tags are read-only under `meta`) — a gap we'd like to
  feed back upstream (see [API feedback](contributing/api-feedback.md)).
- **Markdown image embeds are dropped.** Rich-text writes as Markdown do not
  preserve image embeds (the v3 sanitizer drops them silently); the workaround
  is a `db_html` body via `api_call` (see [escape-hatch](escape-hatch.md)).
- **v3 API must be mounted at `/api/v3/`.** wagtail-mcp dispatches against the
  v3 API mounted at exactly `/api/v3/` — it does not (yet) detect a different
  mount prefix from the OpenAPI schema. A site that mounts the API at another
  prefix (e.g. `/api/v3-preview/`) is unsupported today; automatic prefix
  discovery is a possible future enhancement.
- **Writable fields require `writable=True`.** Only `api_fields` marked
  `writable=True` appear in the v3 create/update schemas. A project whose
  content model exposes a field read-only on the API cannot write it through
  wagtail-mcp until the model marks it writable — the field is silently omitted
  from the write schema rather than erroring.
- **Snippet drafts/live state.** The snippet read schema's `meta` does not
  surface a `live` flag, so agents can't glean publish state from a snippet
  detail read alone (they must know whether the type is draftable).
- Redirects returned by the API are followed transparently (e.g. `pages_find`
  responds with a 302 to the page detail; the tool follows it).
