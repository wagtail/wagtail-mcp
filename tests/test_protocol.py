import contextlib
import json
import signal

import pytest


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}

ACCEPT = "application/json, text/event-stream"


def post(client, payload, token=None):
    headers = {"content_type": "application/json", "HTTP_ACCEPT": ACCEPT}
    if token:
        headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client.post("/mcp/", json.dumps(payload), **headers)


def tools_call_payload(name, arguments=None, request_id=3):
    """Build a JSON-RPC ``tools/call`` payload for a tool call."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }


def call_tool(client, token, name, request_id=10, **arguments):
    """Call a tool over the /mcp/ endpoint and return its parsed result.

    Prefers ``structuredContent`` when the SDK returns it (dict-returning tools
    do); otherwise parses the single text content block as JSON.
    """
    result = call_tool_raw(client, token, name, request_id=request_id, **arguments)
    assert result.get("isError") is False, result
    if "structuredContent" in result:
        return result["structuredContent"]
    text = result["content"][0]["text"]
    return json.loads(text) if text else None


def call_tool_raw(client, token, name, request_id=10, **arguments):
    """Call a tool over the /mcp/ endpoint and return the full CallToolResult dict."""
    response = post(client, tools_call_payload(name, arguments, request_id), token)
    assert response.status_code == 200, response.content
    return response.json()["result"]


@pytest.mark.django_db
def test_initialize_and_tools_list(client, token):
    response = post(client, INIT, token)
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["serverInfo"]["name"] == "wagtail-mcp"
    response = post(client, TOOLS_LIST, token)
    tools = response.json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert names == {
        "whoami",
        "schema_list",
        "schema_detail",
        "api_schema",
        "api_call",
        "pages_list",
        "pages_find",
        "pages_detail",
        "pages_create",
        "pages_update",
        "pages_delete",
        "pages_actions_delete",
        "pages_actions_publish",
        "pages_actions_unpublish",
        "pages_actions_copy",
        "pages_actions_move",
        "pages_actions_revert",
        "pages_actions_convert_alias",
        "pages_actions_create_alias",
        "pages_actions_copy_for_translation",
        "pages_revisions_list",
        "pages_revisions_detail",
        "images_list",
        "images_detail",
        "images_create",
        "images_update",
        "images_delete",
        "documents_list",
        "documents_detail",
        "documents_create",
        "documents_update",
        "documents_delete",
        "snippets_list",
        "snippets_detail",
        "snippets_create",
        "snippets_update",
        "snippets_delete",
        "snippets_actions_delete",
        "snippets_revisions_list",
        "snippets_revisions_detail",
        "snippets_actions_publish",
        "snippets_actions_unpublish",
        "snippets_actions_revert",
        "snippets_actions_copy_for_translation",
        "redirects_list",
        "redirects_find",
        "redirects_detail",
        "redirects_create",
        "redirects_update",
        "redirects_delete",
        "sites_list",
        "sites_detail",
        "sites_create",
        "sites_update",
        "sites_delete",
        "locales_list",
        "locales_detail",
        "locales_create",
        "locales_update",
        "locales_delete",
    }


@pytest.mark.django_db
def test_post_without_token_is_401(client):
    response = post(client, INIT)
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Bearer"


@pytest.mark.django_db
def test_get_is_405(client, token):
    response = client.get(
        "/mcp/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_ACCEPT=ACCEPT
    )
    assert response.status_code == 405


@pytest.mark.django_db
def test_require_auth_false_allows_anonymous(client, settings):
    settings.WAGTAIL_MCP = {"require_auth": False}
    response = post(client, INIT)
    assert response.status_code == 200


@pytest.mark.django_db
def test_malformed_jsonrpc(client, settings, token):
    settings.WAGTAIL_MCP = {"require_auth": True}
    response = post(client, {"jsonrpc": "2.0", "id": 9, "method": "no/such"}, token)
    body = response.json()
    assert "error" in body


@pytest.mark.django_db
def test_unicode_header_does_not_crash_view(client, settings):
    """A non-latin-1 header value must not raise UnicodeEncodeError (M2).

    The ASGI scope builder encodes header values to latin-1; a client sending a
    non-ASCII value (e.g. a Unicode User-Agent) must be tolerated rather than
    turning a benign request into a 500 before auth. With auth required and no
    token, the request should reach the auth gate and return 401, not crash.
    """
    settings.WAGTAIL_MCP = {"require_auth": True}
    response = client.post(
        "/mcp/",
        json.dumps(INIT),
        content_type="application/json",
        HTTP_ACCEPT=ACCEPT,
        HTTP_USER_AGENT="Mozilla/5.0 (x) ünïcode",
    )
    assert response.status_code == 401


@pytest.mark.django_db(transaction=True)
def test_require_auth_false_still_forwards_valid_token(client, token, settings):
    """With require_auth disabled, a presented valid token is still honored (M6).

    require_auth only gates the *rejection* of missing/invalid tokens; a client
    that nonetheless sends a valid token should have it resolved and forwarded so
    authenticated operations (whoami / writes) work as that user.
    """
    settings.WAGTAIL_MCP = {"require_auth": False}
    result = call_tool(client, token, "whoami")
    assert result["user"]["username"] == "admin"


@pytest.mark.django_db(transaction=True)
def test_require_auth_false_anonymous_tool_call_is_error(client, settings):
    """Without a token and auth disabled, an authed-only tool is an MCP error.

    whoami requires v3 authentication; called anonymously it surfaces an isError
    tool result (HTTP 200 at the MCP layer), not an HTTP 401 at the transport.
    """
    settings.WAGTAIL_MCP = {"require_auth": False}
    result = call_tool_raw(client, None, "whoami")
    assert result.get("isError") is True
    text = result["content"][0]["text"]
    assert "401" in text or "Unauthorized" in text or "API token" in text


# MCP 2026-07-28: per-request envelope in ``params._meta`` plus routing headers.
MODERN_VERSION = "2026-07-28"


@contextlib.contextmanager
def fails_after(seconds):
    """Fail instead of hanging the suite when a request never returns."""

    def timed_out(signum, frame):
        raise TimeoutError(f"no response within {seconds}s")

    previous = signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def modern_payload(method, params=None, request_id=1):
    params = dict(params or {})
    params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": MODERN_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def post_modern(client, token, method, params=None):
    with fails_after(10):
        return client.post(
            "/mcp/",
            json.dumps(modern_payload(method, params)),
            content_type="application/json",
            HTTP_ACCEPT=ACCEPT,
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_MCP_METHOD=method,
            HTTP_MCP_PROTOCOL_VERSION=MODERN_VERSION,
        )


@pytest.mark.django_db
def test_discover_does_not_advertise_change_notifications(client, token):
    """listChanged/subscribe promise a subscriptions/listen stream, which the
    stateless endpoint cannot serve; clients open one when they see them."""
    response = post_modern(client, token, "server/discover")
    assert response.status_code == 200, response.content
    capabilities = response.json()["result"]["capabilities"]
    for name in ("tools", "prompts", "resources"):
        assert not capabilities.get(name, {}).get("listChanged"), capabilities
    assert not capabilities.get("resources", {}).get("subscribe"), capabilities


@pytest.mark.django_db
def test_subscriptions_listen_is_method_not_found(client, token):
    response = post_modern(
        client,
        token,
        "subscriptions/listen",
        {"notifications": {"toolsListChanged": True}},
    )
    assert response.status_code == 404, response.content
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32601, "message": "Method not found: subscriptions/listen"},
    }


@pytest.mark.django_db
def test_streamed_reply_does_not_hang(rf, token):
    """The SDK answers subscriptions/listen on its SSE path, which loops on
    ``receive()`` until a disconnect. ``receive()`` must wait after the body
    rather than return it again, or that loop never yields (the request hung
    until the worker was killed). Called below the view's guard on purpose."""
    from wagtail_mcp.views import _build_scope, _handle_stateless

    request = rf.post(
        "/mcp/",
        json.dumps(
            modern_payload(
                "subscriptions/listen", {"notifications": {"toolsListChanged": True}}
            )
        ),
        content_type="application/json",
        HTTP_ACCEPT=ACCEPT,
        HTTP_MCP_METHOD="subscriptions/listen",
        HTTP_MCP_PROTOCOL_VERSION=MODERN_VERSION,
    )
    with fails_after(10):
        response = _handle_stateless(request, _build_scope(request))
    assert json.loads(response.content)["error"]["code"] == -32601


@pytest.mark.django_db
def test_modern_tool_call_still_works(client, token):
    with fails_after(10):
        response = client.post(
            "/mcp/",
            json.dumps(modern_payload("tools/list")),
            content_type="application/json",
            HTTP_ACCEPT=ACCEPT,
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_MCP_METHOD="tools/list",
            HTTP_MCP_PROTOCOL_VERSION=MODERN_VERSION,
        )
    assert response.status_code == 200, response.content
    assert response.json()["result"]["tools"]
