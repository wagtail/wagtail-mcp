# Task runner: https://github.com/casey/just
# Requires: `uv`, `npm`, and `just`.
# Editable package path under `src/` (passed to `coverage run --source`).

# List all the justfile recipes.
help:
    just --list --list-prefix 'just '

# Remove all the Python and Node.js cache files.
clean-pyc:
    find . -name '*.pyc' -exec rm -f {} +
    find . -name '*.pyo' -exec rm -f {} +
    find . -name '*~' -exec rm -f {} +

# Install the dependencies.
install: clean-pyc
    uv sync --dev
    npm ci
    uv run prek

# Lint the server code with uv.
lint-server:
    uv run ruff format --check .
    uv run ruff check .
    SKIP=ruff-check,ruff-format,lint-css,lint-format uv run prek run --all-files

# Lint the client code with Prettier.
lint-client:
    npm run lint --loglevel silent

# Run all linters.
lint: lint-server lint-client

# Format the server code with uv.
format-server:
    uv run ruff check . --fix
    uv run ruff format .
    SKIP=ruff-check,ruff-format,lint-css,lint-format uv run prek run --all-files

# Format the client code with Prettier.
format-client:
    npm run format

# Run all formatters.
format: format-server format-client

# Run tests with pytest.
test:
    uv run --extra agent pytest

test-lowest-deps:
    #!/usr/bin/env bash
    set -euo pipefail
    lowest_python=$(uv run python -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["requires-python"].removeprefix(">=").strip())')
    uv run --isolated --python "$lowest_python" --resolution lowest-direct --extra agent pytest

test-highest-deps:
    uv run --isolated --extra agent --with 'Django, Wagtail' pytest

# Run tests with coverage.
coverage:
    uv run --extra agent pytest --cov wagtail_mcp
    uv run coverage report -m
    uv run coverage html

# Make migrations and migrate the database.
migrate:
    uv run ./demo/manage.py makemigrations
    uv run ./demo/manage.py migrate

# Run the development server at the given host and port.
runserver:
    uv run ./demo/manage.py runserver


# Run the demo under ASGI so the admin agent's SSE endpoint streams
# incrementally. The agent is at /admin/wagtail_mcp/agent/. Requires an ASGI
# server installed separately (adopters choose: uvicorn, daphne, granian, ...).
runserver-asgi:
    cd demo && uv run --with 'uvicorn' uvicorn demo.asgi:application --reload --port 8000

# Build the admin agent's frontend bundle (owned by the frontend session;
# see package.json's build:agent script).
build-agent-js:
    npm run build:agent

# Load the initial data into the database.
load_initial_data:
    uv run ./demo/manage.py load_initial_data

# Open a shell to the demo application.
shell:
    uv run ./demo/manage.py shell

# Run the demo application.
demo: migrate load_initial_data create_demo_api_token runserver

# Create (or refresh) the demo user's wagtail-mcp API token.
# The plaintext is written to demo/.demo_token (gitignored).
# Create (or refresh) the demo user's wagtail-mcp API token.
# The plaintext is written to demo/.demo_token (gitignored).
create_demo_api_token:
    uv run ./demo/manage.py create_demo_api_token

# Install the tools needed to run the agent-behavior eval suite (globally, so
# they stay out of package.json): promptfoo, the OpenCode CLI, and the OpenCode
# SDK that the promptfoo `opencode:sdk` provider uses.
eval-init:
    #!/usr/bin/env bash
    set -euo pipefail
    npm install --global promptfoo @opencode-ai/sdk
    if ! command -v opencode >/dev/null 2>&1; then
        echo "The OpenCode CLI is required for the eval suite and was not found."
        echo "Install it from https://opencode.ai/docs/ — e.g.:"
        echo "  npm install --global opencode-ai"
        exit 1
    fi
    promptfoo --version
    opencode --version

# Reset the demo database and issue a fresh API token for the eval suite.
# This deletes demo/db.sqlite3 and demo/media, so it must not run while the
# demo server is using them. It does not start the server.
eval-setup:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://localhost:8000/mcp/ 2>/dev/null || true)" != "000" ]; then
        echo "The demo server appears to be running (reached /mcp/, method check answered)." >&2
        echo "Stop it first (Ctrl+C on 'just demo', or kill the runserver) before eval-setup,"
        echo "because it will replace demo/db.sqlite3 and demo/media underneath it." >&2
        exit 1
    fi
    rm -f demo/db.sqlite3
    rm -rf demo/media
    uv run ./demo/manage.py migrate
    uv run ./demo/manage.py load_initial_data
    uv run ./demo/manage.py create_demo_api_token
    echo
    echo "Demo reset complete. Run:"
    echo "  1. 'just demo' to start the server (or your own runserver) in another terminal"
    echo "  2. 'just eval' to run the suite"

# Run the Promptfoo agent-behavior eval suite against the running demo site.
# Requires the demo server to be up (`just demo` in another terminal). Exports
# OPENCODE_CONFIG=evals/opencode.json, a per-run unique id (so reruns don't
# collide in the CMS), and the demo token from demo/.demo_token.
eval:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! command -v promptfoo >/dev/null 2>&1; then
        echo "promptfoo is not installed — run 'just eval-init' first." >&2
        exit 1
    fi
    if [ ! -f demo/.demo_token ]; then
        echo "demo/.demo_token is missing — run 'just eval-setup' (and start the demo) first." >&2
        exit 1
    fi
    if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://localhost:8000/mcp/ 2>/dev/null || true)" = "000" ]; then
        echo "The demo server/MCP endpoint does not respond at http://localhost:8000/mcp/." >&2
        echo "Start it in another terminal with 'just demo' (or your own runserver), then retry." >&2
        exit 1
    fi
    mkdir -p evals/results
    export OPENCODE_CONFIG="$(pwd)/evals/opencode.json"
    export WAGTAIL_DEMO_TOKEN="$(cat demo/.demo_token)"
    export WAGTAIL_EVAL_BASE_URL="${WAGTAIL_EVAL_BASE_URL:-http://localhost:8000}"
    export WAGTAIL_EVAL_RUN_ID="${WAGTAIL_EVAL_RUN_ID:-eval-$(date +%s)-"$$"}"
    shift || true
    promptfoo eval -c evals/promptfooconfig.yaml --no-cache --no-share \
        --output evals/results/latest.json \
        "$@"

# Open the promptfoo web dashboard for the latest eval run.
eval-view:
    promptfoo view
