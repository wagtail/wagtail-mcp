"""Streamable HTTP endpoint for the MCP server.

See docs/contributing/architecture.md.
"""

from asgiref.sync import async_to_sync
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings

from wagtail_mcp import auth
from wagtail_mcp.server import get_server
from wagtail_mcp.settings import get_config


def _encode_header(value):
    """Encode a header name/value for ASGI, tolerating non-latin-1 content.

    Django's ``request.headers`` values are str; ASGI requires bytes. RFC 7230
    limits header bytes to US-ASCII, but a client may send non-ASCII (e.g. a
    Unicode User-Agent). Encoding defensively (drop the unencodable bytes)
    avoids a 500 before auth instead of a benign request crashing the view.
    """
    return value.encode("latin-1", "ignore")


def _scope_headers(request):
    """Django request headers → ASGI ``[(name_bytes, value_bytes)]`` list."""
    return [
        (_encode_header(name.lower()), _encode_header(value))
        for name, value in request.headers.items()
    ]


def _build_scope(request):
    """Synthesize a minimal ASGI ``http`` scope describing ``request``."""
    http_version = request.META.get("SERVER_PROTOCOL", "HTTP/1.1").rsplit("/", 1)[-1]
    return {
        "type": "http",
        "http_version": http_version,
        "method": request.method,
        "scheme": request.scheme,
        "path": request.path_info or "/",
        "raw_path": (request.path_info or "/").encode("latin-1"),
        "query_string": request.META.get("QUERY_STRING", "").encode("latin-1"),
        "root_path": "",
        "headers": _scope_headers(request),
        "client": ("127.0.0.1", 0),
        "server": (request.get_host(), request.META.get("SERVER_PORT", "80")),
    }


def _handle_stateless(request, scope):
    """Run one stateless MCP request; return the collected ``HttpResponse``."""
    body = request.body

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    start_message = {}
    body_chunks = []

    async def send(message):
        msg_type = message["type"]
        if msg_type == "http.response.start":
            start_message["status"] = message["status"]
            start_message["headers"] = message.get("headers", [])
        elif msg_type == "http.response.body":
            body_chunks.append(message.get("body", b""))

    async def run_request():
        server = get_server()
        manager = StreamableHTTPSessionManager(
            app=server._lowlevel_server,  # SDK-internal transport hook
            json_response=True,
            stateless=True,
            security_settings=TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            ),
        )
        async with manager.run():
            await manager.handle_request(scope, receive, send)

    async_to_sync(run_request)()

    status = start_message.get("status", 500)
    response_headers = {}
    for name, value in start_message.get("headers", []):
        response_headers[name.decode("latin-1").lower()] = value.decode("latin-1")
    content_type = response_headers.pop("content-type", "application/json")

    response = HttpResponse(
        b"".join(body_chunks),
        status=status,
        content_type=content_type,
    )
    for name, value in response_headers.items():
        if name.lower() != "content-length":
            response[name] = value
    return response


@csrf_exempt
@require_http_methods(["POST"])
def mcp_endpoint(request):
    """MCP endpoint: POST JSON-RPC messages via stateless Streamable HTTP.

    Non-POST methods yield 405 (from ``require_http_methods``) — this endpoint
    does not serve the SSE GET stream; stateless JSON responses only.
    """
    config = get_config()
    token = auth.resolve_bearer(request)
    if config.get("require_auth", True) and token is None:
        response = JsonResponse({"error": "invalid_token"}, status=401)
        response["WWW-Authenticate"] = "Bearer"
        return response

    context_token = auth.current_token.set(token)
    try:
        try:
            host = request.get_host()
        except Exception:  # DisallowedHost and friends
            host = None
        context_host = auth.current_host.set(host)
        # ``request.scheme`` honours SECURE_PROXY_SSL_HEADER, so behind a
        # TLS-terminating proxy this is "https" for the usual browser/API
        # traffic the MCP endpoint serves.
        context_scheme = auth.current_scheme.set(request.scheme)
        try:
            return _handle_stateless(request, _build_scope(request))
        finally:
            auth.current_scheme.reset(context_scheme)
            auth.current_host.reset(context_host)
    finally:
        auth.current_token.reset(context_token)
