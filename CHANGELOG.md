# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-09-23

### Fixed

- Support `SECURE_SSL_REDIRECT=True`. ty [@ivanscm](https://github.com/ivanscm)!

### Added

- Optional, experimental admin agent: use the same MCP tools as a chat in the Wagtail admin, over AG-UI.

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
