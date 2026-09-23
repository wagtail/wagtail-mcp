import json
import uuid

import pytest

from asgiref.sync import sync_to_async
from conftest import make_token
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.middleware.csrf import _get_new_csrf_string
from django.test import AsyncClient
from django.utils.timezone import now
from mcp.server.mcpserver.exceptions import ToolError
from wagtail.models import Page

from wagtail_mcp import auth
from wagtail_mcp.agent import auth as agent_auth
from wagtail_mcp.agent import registry as agent_registry
from wagtail_mcp.agent.availability import try_reverse_agent_endpoint
from wagtail_mcp.server import get_server


pytestmark = pytest.mark.django_db

ENDPOINT = "/admin/wagtail_mcp/agent/api/"


@pytest.fixture
def root_page():
    # Wagtail's default home page (depth 2) from migrations.
    return Page.objects.filter(depth=2).first() or Page.objects.get(depth=1)


def _unique(name: str) -> str:
    """A per-run username suffix: async tests hold connections whose
    transactions the pytest-django teardown cannot always reach, so reusing a
    fixed username across tests can collide with a not-yet-rolled-back row."""
    return f"{name}{uuid.uuid4().hex[:8]}"


def make_admin(client):
    """Create a superuser, log them in, and return the user."""

    user = get_user_model().objects.create_superuser(
        _unique("agentadmin"), "a@example.com", "pw"
    )
    client.force_login(user)
    return user


def make_non_staff_admin(client):
    """A user with admin access but ``is_staff=False`` — past Wagtail's admin
    gate, refused by the agent's own staff check."""

    user = get_user_model().objects.create_user(
        _unique("agentnostaff"), "n@example.com", "pw", is_staff=False
    )
    user.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="wagtailadmin", codename="access_admin"
        )
    )
    client.force_login(user)
    return user


def run_payload(content="hello"):
    """A minimal RunAgentInput body."""
    return {
        "threadId": "t-1",
        "runId": "r-1",
        "messages": [
            {"id": "m-1", "role": "user", "content": content},
        ],
        "tools": [],
        "state": {},
        "context": [],
        "forwardedProps": {},
    }


async def make_non_staff_admin_async(client):
    """Async flavour of `make_non_staff_admin` (ORM off the event loop)."""

    @sync_to_async
    def _make():
        user = get_user_model().objects.create_user(
            _unique("agentnostaff"), "n@example.com", "pw", is_staff=False
        )
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="wagtailadmin", codename="access_admin"
            )
        )
        return user

    user = await _make()
    await client.aforce_login(user)
    return user


async def make_admin_async(client, username="agentadmin"):
    """Async flavour of `make_admin` (ORM off the event loop)."""

    return await sync_to_async(get_user_model().objects.create_superuser)(
        username, "a@example.com", "pw"
    )


def seed_csrf(client):
    """Seed a valid CSRF cookie on ``client`` and return the token to send.

    Exercises the real CSRF validation path: the middleware compares the
    ``X-CSRFToken`` header against the (unmasked) secret held in the
    ``csrftoken`` cookie, so seeding the cookie with a fresh secret and
    echoing it in the header passes — anything else does not. Django's test
    clients default to ``enforce_csrf_checks=False``, which is why tests that
    want to prove the check must seed the cookie themselves.
    """

    token = _get_new_csrf_string()
    client.cookies[settings.CSRF_COOKIE_NAME] = token
    return token


async def post_run_async(client, payload=None):
    """POST a RunAgentInput through the async (ASGI) test client.

    The CSRF cookie is seeded (see `seed_csrf`) so the request passes the
    middleware's real CSRF validation — the same guarantee the browser gets
    from ``data-csrf-token``.
    """
    token = seed_csrf(client)
    return await client.post(
        ENDPOINT,
        data=json.dumps(payload or run_payload()),
        content_type="application/json",
        HTTP_ACCEPT="text/event-stream",
        headers={"X-CSRFToken": token},
    )


async def parse_sse(response):
    """Drain a StreamingHttpResponse's SSE frames into event dicts."""
    chunks = []
    async for chunk in response.streaming_content:
        chunks.append(chunk)
    body = b"".join(chunks).decode()
    events = []
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if frame.startswith("data: "):
            events.append(json.loads(frame[len("data: ") :]))
    return events


def event_types(events):
    return [event["type"] for event in events]


# --- Tool bridge --------------------------------------------------------------


def test_registry_mirrors_the_mcp_tool_inventory():
    """Every MCP tool is bridged into the AG-UI registry, same-named."""
    agent_registry.reset_cache()
    registry = agent_registry.build_registry()
    mcp_names = {tool.name for tool in get_server()._tool_manager.list_tools()}
    assert len(registry) == len(mcp_names)
    assert {binding.spec.name for binding in registry} == mcp_names


@pytest.mark.parametrize(
    "name,expected",
    [
        ("pages_list", False),  # read-only
        ("pages_create", True),  # write
        ("pages_delete", True),  # destructive
    ],
)
def test_registry_destructiveness_follows_mcp_annotations(name, expected):
    """MCP annotations map onto AG-UI's destructive flag."""
    agent_registry.reset_cache()
    binding = agent_registry.build_registry().get(name)
    assert binding.spec.destructive is expected


def test_registry_tool_executes_through_the_dispatch_layer():
    """A bridged tool is the real callable: calling it via the registry
    dispatches through v3 (acting on ``auth.current_token``)."""

    agent_registry.reset_cache()
    token = make_token()  # superuser + APIToken
    context = auth.current_token.set(token)
    try:
        binding = agent_registry.build_registry().get("whoami")
        result = binding.spec.fn()
        assert result["user"]["username"] == "admin"
    finally:
        auth.current_token.reset(context)


def test_bridged_tool_surfaces_api_errors_as_tool_errors():
    """An APIError inside a bridged tool surfaces as a ToolError (the same
    translation the MCP transport applies), not a 500."""

    agent_registry.reset_cache()
    binding = agent_registry.build_registry().get("pages_detail")
    with pytest.raises(ToolError):
        binding.spec.fn(page_id=999999999)


def test_bridged_write_survives_secure_ssl_redirect(settings, root_page):
    """A bridged tool's write must persist under ``SECURE_SSL_REDIRECT=True``
    (issue #5, agent entry point).

    ``_as_acting_user`` must forward the run's acting scheme into
    ``auth.current_scheme``: without it the in-process client speaks plain
    http, SecurityMiddleware 301s the POST, and the client follows it as a
    GET — the write silently saves nothing.
    """

    from wagtail_mcp.test.models import ContentPage

    agent_registry.reset_cache()
    settings.SECURE_SSL_REDIRECT = True
    settings.ALLOWED_HOSTS = ["*"]
    scheme_context = agent_registry._acting_scheme.set("https")
    token_context = auth.current_token.set(make_token())  # superuser + APIToken
    try:
        binding = agent_registry.build_registry().get("pages_create")
        data = binding.spec.fn(
            type="wagtail_mcp_test.ContentPage",
            parent_id=root_page.pk,
            title="Agent redirect-proof",
        )
    finally:
        auth.current_token.reset(token_context)
        agent_registry._acting_scheme.reset(scheme_context)
    assert data["title"] == "Agent redirect-proof"
    assert "items" not in data  # a list payload means POST degraded to GET
    assert ContentPage.objects.filter(title="Agent redirect-proof").exists()


# --- Endpoint auth -----------------------------------------------------------


async def test_run_endpoint_anonymous_is_unauthorized(async_client):
    # Outside Wagtail's admin URLs, so this is the endpoint's own 401 JSON,
    # not an admin login redirect. See docs/admin-agent.md.
    response = await async_client.post(
        ENDPOINT,
        data=json.dumps(run_payload()),
        content_type="application/json",
    )
    assert response.status_code == 401
    assert response["Content-Type"].startswith("application/json")


async def test_run_endpoint_non_staff_admin_gets_json_403(async_client):
    await make_non_staff_admin_async(async_client)
    response = await post_run_async(async_client)
    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")


async def test_run_endpoint_requires_csrf_token():
    """CSRF is enforced (session auth): with checks on, a POST without an
    X-CSRFToken header is rejected by the middleware — 403, not a run."""

    client = AsyncClient(enforce_csrf_checks=True)
    user = await make_admin_async(client, username=_unique("csrfadmin"))
    await client.aforce_login(user)
    response = await client.post(
        ENDPOINT,
        data=json.dumps(run_payload()),
        content_type="application/json",
    )
    assert response.status_code == 403


async def test_run_endpoint_accepts_matching_csrf_token():
    """The happy path: a seeded cookie + matching header passes the real CSRF
    validation — the same guarantee the browser gets from the mount div's
    data-csrf-token."""

    client = AsyncClient(enforce_csrf_checks=True)
    user = await make_admin_async(client, username=_unique("csrfokadmin"))
    await client.aforce_login(user)
    token = seed_csrf(client)
    response = await client.post(
        ENDPOINT,
        data=json.dumps(run_payload()),
        content_type="application/json",
        headers={"X-CSRFToken": token},
    )
    # Not a 403: the CSRF check passed (whatever status follows is past the
    # middleware — the run itself).
    assert response.status_code != 403


# --- Endpoint run (TestModel) --------------------------------------------------
# The end-to-end streaming test lives in test_agent_run.py: a real run
# dispatches its tool calls through worker threads whose DB connections
# cannot see a wrapping test transaction, so it needs a transactional DB —
# whose post-test flush must not land between other modules' tests.


async def test_run_endpoint_invalid_run_input_is_400(async_client):
    user = await make_admin_async(async_client)
    await async_client.aforce_login(user)
    response = await post_run_async(async_client, payload={"bad": "shape"})
    # A dict missing required RunAgentInput fields parses as JSON but fails
    # validation — either way, not a 500.
    assert response.status_code in (400, 422)


def test_tools_catalog_lists_bridged_tools(client):
    make_admin(client)
    response = client.get(f"{ENDPOINT}tools/")
    assert response.status_code == 200
    catalog = response.json()
    names = {entry["name"] for entry in catalog}
    assert "pages_list" in names
    assert "whoami" in names


def test_tools_catalog_anonymous_is_unauthorized(client):
    # Same 401-JSON answer as the run endpoint (own gate, not an admin
    # login redirect).
    response = client.get(f"{ENDPOINT}tools/")
    assert response.status_code == 401
    assert response["Content-Type"].startswith("application/json")


# --- Page rendering -----------------------------------------------------------


def test_agent_page_renders_mount_div_for_staff(client):
    make_admin(client)
    response = client.get("/admin/wagtail_mcp/agent/")
    assert response.status_code == 200
    html = response.content.decode()
    assert 'id="wagtail-mcp-agent-root"' in html
    assert 'data-endpoint="/admin/wagtail_mcp/agent/api/"' in html
    assert 'data-csrf-token="' in html
    assert 'data-csrf-token=""' not in html
    assert "/static/wagtail_mcp/js/agent.js" in html


def test_agent_page_anonymous_redirects_to_login(client):
    response = client.get("/admin/wagtail_mcp/agent/")
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_admin_home_shows_agent_menu_item(client):
    """Mounted endpoint: the sidebar menu item links to the agent page."""
    make_admin(client)
    response = client.get("/admin/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "/admin/wagtail_mcp/agent/" in html
    # The chat itself only mounts on the agent page, not the homepage.
    assert 'id="wagtail-mcp-agent-root"' not in html
    assert "wagtail_mcp/js/agent.js" not in html


def test_agent_page_renders_setup_instructions_when_unmounted(settings, client):
    """Without the agent URLconf mount, the agent page degrades to setup
    instructions instead of the chat mount (see docs/admin-agent.md)."""
    settings.ROOT_URLCONF = "urls_without_agent"
    from django.urls import clear_url_caches

    clear_url_caches()
    make_admin(client)
    response = client.get("/admin/wagtail_mcp/agent/")
    clear_url_caches()
    assert response.status_code == 200
    html = response.content.decode()
    assert 'id="wagtail-mcp-agent-root"' not in html
    assert "wagtail_mcp/js/agent.js" not in html


# --- Opt-in gating ------------------------------------------------------------


def test_gated_surfaces_visible_when_endpoint_mounted(client):
    """Mounted endpoint: menu item, chat page and chat mount all render."""
    make_admin(client)
    homepage = client.get("/admin/").content.decode()
    page = client.get("/admin/wagtail_mcp/agent/").content.decode()
    assert try_reverse_agent_endpoint() == "/admin/wagtail_mcp/agent/api/"
    assert "/admin/wagtail_mcp/agent/" in homepage  # menu item
    assert 'id="wagtail-mcp-agent-root"' in page
    assert 'data-endpoint="/admin/wagtail_mcp/agent/api/"' in page
    assert 'data-csrf-token="' in page
    assert 'data-csrf-token=""' not in page


def test_unmounted_endpoint_hides_every_agent_surface(settings, client):
    """Without the agent URLconf mount, the admin renders with no agent UI.

    Regression: the admin homepage and the agent page both 500'd with
    ``NoReverseMatch: 'wagtail_mcp_agent' is not a registered namespace``.
    """
    settings.ROOT_URLCONF = "urls_without_agent"
    from django.urls import clear_url_caches

    clear_url_caches()
    make_admin(client)
    response = client.get("/admin/")
    assert response.status_code == 200
    html = response.content.decode()
    assert 'id="wagtail-mcp-agent-root"' not in html
    assert "wagtail_mcp/js/agent.js" not in html
    assert "/admin/wagtail_mcp/agent/" not in html


def test_unmounted_endpoint_hides_menu_item_for_every_admin_page(client, settings):
    """The menu gate runs per request (``AgentMenuItem.is_shown``), on any
    admin page, not only the homepage."""
    settings.ROOT_URLCONF = "urls_without_agent"
    from django.urls import clear_url_caches

    clear_url_caches()
    make_admin(client)
    response = client.get("/admin/pages/")
    clear_url_caches()
    assert response.status_code == 200
    assert "/admin/wagtail_mcp/agent/" not in response.content.decode()


# --- Auth bridge --------------------------------------------------------------


def test_get_api_token_mints_and_reuses(client):
    agent_auth.clear_cache()
    user = make_admin(client)

    first = agent_auth.get_api_token(user)
    tokens = user.api_tokens.filter(name=agent_auth.TOKEN_NAME)
    assert tokens.count() == 1

    # The second call reuses the cached plaintext — no second token row.
    second = agent_auth.get_api_token(user)
    assert second == first
    assert tokens.count() == 1


def test_get_api_token_honors_revocation(client):

    agent_auth.clear_cache()
    user = make_admin(client)

    first = agent_auth.get_api_token(user)
    user.api_tokens.filter(name=agent_auth.TOKEN_NAME).update(revoked_at=now())
    second = agent_auth.get_api_token(user)
    assert second != first
    # The revoked row was replaced by a fresh one.
    assert user.api_tokens.filter(name=agent_auth.TOKEN_NAME).count() == 1
