# Tasks

## Set up a checkout

Requirements: [`uv`](https://github.com/astral-sh/uv), [`just`](https://github.com/casey/just), [`prek`](https://prek.j178.dev/).

```sh
git clone git+https://github.com/org-name-or-username/wagtail-mcp
cd wagtail-mcp
just install
just demo
```

`just demo` migrates the demo site, loads fixtures, and starts the server. The demo token and client config are in `demo/README.md`.

## Tests

Pytest modules live in `tests/`, next to the existing files. The Django test app and its settings are `src/wagtail_mcp/test/`.

## Adding a tool

Add a `register(server)` wrapper in `src/wagtail_mcp/tools/`. Name it after the v3 `operation_id` when the operation is one an agent should reach for; otherwise leave it to `api_call`. Auth and permissions stay in the v3 API — the wrapper flattens arguments and shapes the response. Document the tool in the [tool reference](../tools.md).

## Agent-behavior evals

`evals/` checks that a model uses the tools and that the demo site's state changes. Pytest proves the tools are callable; this suite proves an agent reaches for them. Design, graders, and cases are in [`evals/README.md`](../../evals/README.md).

The suite is not part of `just test` or CI. It spends tokens, the runs are noisy, and it needs a live demo server plus an API key.

```sh
just eval-init          # promptfoo, OpenCode CLI, and @opencode-ai/sdk, installed globally
just eval-setup         # reset the demo DB and issue a fresh API token
just demo               # the site the suite calls
just eval               # run the suite
just eval --repeat 3    # repeat before trusting a delta
just eval-view          # dashboard for the latest run
```

`just eval` reads the model-provider API key from the environment (see
`evals/README.md`) and the demo token in `demo/.demo_token`. The global
installs stay out of `package.json` so a checkout that never runs evals does
not pay for them.

## Code review

Open a pull request with a summary of the change and the steps a reviewer uses to test it. Include tests for the behavior you changed.
