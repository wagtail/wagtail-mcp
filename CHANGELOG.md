# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- The `agent` extra no longer pins `uvicorn`: the ASGI server is the
  adopter's choice (`uvicorn`, `daphne`, ...). The demo's `just runserver-asgi`
  injects `uvicorn` itself.
- Documentation is split into user guides and reference under `docs/`, and contributor notes under `docs/contributing/`.

### Fixed

- The admin agent is now fully opt-in: without the agent URLconf mount, no
  agent UI appears in the Wagtail admin, and the admin homepage no longer
  500s. `/admin/wagtail_mcp/agent/` renders setup instructions instead.
- The agent chat now mounts only on `/admin/wagtail_mcp/agent/` — the admin
  homepage panel and summary item are gone.
- `get_agent_config()` no longer falls back to environment variables for the
  agent's provider credentials: set them in `WAGTAIL_MCP`
  (`agent_api_key`, `agent_base_url`).
- CI test jobs now install the `agent` extra (`uv sync --extra agent` /
  `--extra agent`), fixing `ModuleNotFoundError: django_ag_ui` in
  `test_flow_agent_run.py`, and the compatibility job's undefined
  `matrix.packages` reference.

### Added

- Experimental admin agent: the MCP tools as a chat in the Wagtail admin, over AG-UI. Requires the `agent` extra, an ASGI server, and mounting the endpoint URLconf. See [docs/admin-agent.md](docs/admin-agent.md).

## [0.2.0] - 2026-09-18

### Added

- Paginated tools now state the maximum `limit` in their descriptions, read from Wagtail's `WAGTAILAPI_LIMIT_MAX`.
- `pages_create` and `pages_update` now accept a `fields` dict for any writable field of the page type.
- `pages_detail` now reports `meta.seo_title` and `meta.search_description`.
- `images_create` accepts an optional `description`.
- `images_update` accepts `title` and `description`.

### Fixed

- Make sure the package works with production-restricted `ALLOWED_HOSTS`
- Detail tools no longer silently drop fields the v3 API returned.

## [0.1.0] - 2026-08-27

First release ✨🤖 vibe-coded prototype built with pi and Kimi K3.

Please share your feedback on our plans: [CMS with AI, not AI CMS: Wagtail 8.0’s new API](https://wagtail.org/blog/cms-with-ai-not-ai-cms-wagtail-80s-new-api/).

<!-- TEMPLATE - keep below to copy for new releases -->
<!--


## [x.y.z] - YYYY-MM-DD

### Added

- ...

### Changed

- ...

### Removed

- ...

-->
