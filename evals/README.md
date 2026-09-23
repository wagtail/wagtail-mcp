# wagtail-mcp agent-behavior evals

Promptfoo eval suite that drives the **OpenCode SDK** against the wagtail-mcp
MCP server on the demo site, to verify a real model actually **uses** the
tools — and that using them changes real Wagtail CMS state.

This is the "does the robot do the thing" layer of the test strategy. The
layer-1–3 pytest suites prove the tools are *callable and correct*; this suite
proves they are *ergonomic enough for an agent to reach for*, which is the
failure mode a hand-written suite cannot catch.

## How it works

The suite runs **one prompt through two arms** over the same model
(`deepseek/deepseek-v4-flash-0731`, served by the configured eval provider —
TensorX in this checkout):

| arm | tools available | what it measures |
|-----|-----------------|------------------|
| `baseline` | none at all (`tools: {"*": false}`, wagtail MCP not configured) | what the model can say/guess from memory with no CMS access — the control |
| `mcp` | only the wagtail MCP tools (`tools: {"*": false, "wagtail_*": true}`) | whether the model discovers and uses the real tools to complete a task |

Both arms share the identical `custom_agent` (temperature 0, up to 20 steps)
and the identical prompt, so the only variable between them is tool access.
The `mcp` arm points the `wagtail` MCP server at the running demo site
(`http://localhost:8000/mcp/`, bearer token from env) via `evals/opencode.json`.

## Grading: state, not prose

Each case's main assertion is a **state-graded** check in
`evals/graders/state_checks.py` that calls the demo v3 API over HTTP
(stdlib `urllib`, no third-party deps) and asserts the CMS actually changed:

- `blog_post_exists` — a `blog.BlogPage` with the unique title exists under
  the Blog index (id 4) and its body carries the expected text.
- `image_uploaded` — an image with the expected title exists.
- `snippet_created` — a `blog.Person` with the expected first name exists.
- `redirect_created` — a redirect for `/old-<unique>/` exists.
- `revision_reverted` — page 5 has ≥ 2 revisions (a publish + a revert).
- `whoami` / `lists_child_pages` — prose-graded (the truth is in the model's
  answer, not a mutation).

Shared first assertion on every case: the **empty-output guard** — a blank
response is a provider error (rate limit / dropped connection), not a model
failure, and is failed loudly and named as such.

Each write case embeds a per-run unique `suffix` (from
`{{ env.WAGTAIL_EVAL_RUN_ID }}`) so reruns don't collide in the CMS.

## Prerequisites

- `just eval-init` — installs `promptfoo` + `@opencode-ai/sdk` globally plus
  the OpenCode CLI (kept out of `package.json`).
- `just eval-setup` — resets the demo DB to fixtures and issues a fresh API
  token (`demo/.demo_token`). **Stop the demo server first** — it deletes
  `demo/db.sqlite3` and `demo/media`.
- A running demo site: `just demo` (or your own `runserver`) with the v3 API
  and `/mcp/` mounted.
- **Env vars**: `TENSORX_API_KEY` (the model under test and the rubric grader
  run on the provider configured in `evals/opencode.json` — TensorX in this
  checkout). `just eval` populates `WAGTAIL_DEMO_TOKEN` from
  `demo/.demo_token`, `WAGTAIL_EVAL_BASE_URL` (default
  `http://localhost:8000`), and `WAGTAIL_EVAL_RUN_ID` (per-run unique id).

## Run

```sh
just eval-setup      # reset the demo DB (server must be stopped)
just demo            # start the server (in another terminal)
just eval            # run the suite
just eval --repeat 3 # agent runs are noisy; repeat before trusting a delta
just eval-view       # dashboard for the latest run
```

`just eval` additionally sets `OPENCODE_CONFIG=$(pwd)/evals/opencode.json`, so
the OpenCode SDK provider resolves the model/provider and the wagtail MCP
server from that file. Output goes to `evals/results/latest.json` (gitignored).

> The suite is **not** part of the default `just test`/CI gate: it is
> token-heavy, noisy, and needs a live demo server + API key.

## Cases

| # | case | tools expected | grader |
|---|------|----------------|--------|
| 1 | Identify the authenticated user | `whoami` | state (prose) |
| 2 | List the Home page's child pages | `pages_list` | state (prose) |
| 3 | Create a draft blog post under Blog | `schema_detail` → `pages_list` → `pages_create` | state (API) |
| 4 | Upload a 1×1 GIF image | `images_create` | state (API) |
| 5 | Create a `blog.Person` snippet | `snippets_create` | state (API) |
| 6 | Create a permanent redirect | `redirects_create` | state (API) |
| 7 | Create-then-revert a page revision | `pages_update` → `api_call` (`pages_actions_revert`) | state (API) |

## Known quirks (documented during authoring)

- **OpenCode MCP tool namespacing.** MCP tools are exposed as
  `<server>_<tool>` (e.g. `wagtail_whoami`). Re-enabling only them under a
  `tools: {"*": false}` umbrella requires the glob key `"wagtail_*": true`;
  the server-name key `"wagtail": true` alone does **not** enable its tools.
  Verified empirically against OpenCode 1.18.x.
- **`mcp` must be configured per provider arm.** `evals/opencode.json` holds
  the canonical wagtail server entry for manual/client use; the `mcp` provider
  arm re-declares it (`url`, bearer `headers`) so the baseline arm genuinely
  has no CMS tools (no `mcp` config).
- **State graders call the real API.** They are strict stdlib-only HTTP GET
  clients; no `requests` dependency is needed at runtime.
- **Empty-output guard is shared.** Every row inherits the provider-error
  guard via `defaultTest` before its specific state assertion.

---

## First run results

First complete run: `eval-cUQ` (2026-08-24), 14 cells (7 cases × 2 arms), ~32 s,
~101k tokens, **MCP arm 7/7 passed, baseline 2/7** (9/14 overall, 64%).

Per case:

| # | case | baseline | mcp |
|---|------|:--------:|:---:|
| 1 | whoami | ✅ (memory) | ✅ |
| 2 | list child pages | ❌ | ✅ |
| 3 | draft blog post + body | ❌ | ✅ |
| 4 | image upload | ❌ | ✅ |
| 5 | blog.Person snippet | ❌ | ✅ |
| 6 | permanent redirect | ❌ | ✅ |
| 7 | create-then-revert revision | ✅ (crosstalk) | ✅ |

The `mcp` arm completed every mutating task against the live demo CMS. The
baseline failed everything that requires real CMS state (it has no tools and
is graded against actual state, so any told-you-so answer fails) — the two
baseline passes are rubric artifacts, not tool evidence: case 1 (whoami)
scores on the model naming `admin` from memory, and case 7 (revert) shares the
CMS instance with the `mcp` arm, so its revision-count assertion can already
be satisfied even though the baseline mutated nothing.

### Caveats

- **Eval noise.** Agent runs vary run-to-run; repeat before trusting a delta:
  `just eval --repeat 3`.
- **Arms share one CMS instance.** Both arms run against the *same* demo site,
  so a shared-state grader can observe another arm's mutations (case 7 above).
  Future refinement: add the arm label to each run's unique suffix so arms are
  distinguishable / isolated.
- **Baseline prose results are memory, not tool evidence.** whoami (case 1) is
  deliberately gradeable from the correct answer regardless of arm.
- **`revision_reverted` is a heuristic** (`count >= 2`), so it can pass without
  a real revert if the seeded revision count already suffices; a future
  exact-content assertion would pin it.
