import base64
import json as json_module

from unittest import mock

import pytest

from wagtail.images import get_image_model
from wagtail.models import Page, Site

from wagtail_mcp import auth, dispatch
from wagtail_mcp.dispatch import call_operation, clear_caches, openapi, operation_map
from wagtail_mcp.errors import APIError
from wagtail_mcp.test.models import ContentPage


pytestmark = pytest.mark.django_db


@pytest.fixture
def root_page():
    # Wagtail's default home page (depth 2) from migrations.
    return Page.objects.filter(depth=2).first() or Page.objects.get(depth=1)


def test_operation_map_known_ids():
    ops = operation_map()
    # Exact (method, path): paths match the OpenAPI absolute paths (including
    # the /api/v3/ mount prefix) because the Django test client needs the full
    # mounted URL.
    assert ops["whoami"] == ("get", "/api/v3/whoami/")
    assert ops["pages_create"] == ("post", "/api/v3/pages/")
    assert ops["pages_detail"] == ("get", "/api/v3/pages/{page_id}/")
    assert ops["images_create"][0] == "post"
    # The locales router is mounted only when ``wagtail.locales`` is installed;
    # this pins that the test settings include it (regression for task 6 review).
    assert "locales_list" in ops
    assert "locales_detail" in ops


def test_call_operation_get_with_query(root_page, token):
    hostname = "example.test"
    Site.objects.create(hostname=hostname, root_page=root_page, is_default_site=False)
    data = call_operation("sites_list", query={"limit": 10}, token=token)
    assert data["count"] >= 1
    hostnames = [item["hostname"] for item in data["items"]]
    assert hostname in hostnames


def test_call_operation_unauthorized_raises():
    bad_token = "wagtail_invalidtoken"  # noqa: S105  -- deliberately invalid bearer, not a real credential
    with pytest.raises(APIError) as exc:
        call_operation("pages_create", body={}, token=bad_token)
    assert exc.value.status in (401, 403)


def test_call_operation_404(token, root_page):
    with pytest.raises(APIError) as exc:
        call_operation(
            "pages_detail",
            path_params={"page_id": 999999},
            token=token,
        )
    assert exc.value.status == 404


def test_call_operation_validation_problem(token, root_page):
    with pytest.raises(APIError) as exc:
        call_operation(
            "pages_create",
            body={"meta": {"type": "wagtail_mcp_test.ContentPage"}},
            token=token,
        )
    assert exc.value.status == 422
    assert exc.value.problem["errors"]


def test_upload_image_multipart(root_page, token):
    gif = base64.b64decode(
        "R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw=="
    )
    data = call_operation(
        "images_create",
        form={"title": "dispatch-test"},
        files={"file": ("pixel.gif", gif, "image/gif")},
        token=token,
    )
    assert data["title"] == "dispatch-test"
    assert get_image_model().objects.filter(title="dispatch-test").exists()


def test_openapi_cached_and_clearable():
    first = openapi()
    assert first is openapi()
    openapi.cache_clear()
    assert openapi() is not first


def test_openapi_forwards_current_host(settings):
    """With a strict ALLOWED_HOSTS, openapi() must forward the caller's Host.

    Production runs with ``DEBUG=False`` and an explicit ``ALLOWED_HOSTS``
    list, so Django's test client default of ``testserver`` fails host
    validation and the in-process fetch of ``/openapi.json`` answers 400 —
    breaking every tool call (they all resolve operations through the schema).
    The dispatch layer must forward ``auth.current_host`` like
    ``call_operation()`` does.
    """

    settings.ALLOWED_HOSTS = ["cms.example.com"]
    openapi.cache_clear()
    context = auth.current_host.set("cms.example.com")
    try:
        schema = openapi()
        assert "paths" in schema
    finally:
        auth.current_host.reset(context)
        openapi.cache_clear()


def test_secure_follows_current_scheme():
    """_secure() mirrors the served request's scheme, defaulting to http.

    An outer https request must dispatch as secure (``secure=True``) so
    ``SECURE_SSL_REDIRECT`` does not 301 it; anything else keeps the
    historical plain-http behaviour (scheme *and* port — Wagtail resolves
    sites on hostname+port, so the default must not change which site
    absolute URLs resolve against).
    """

    assert auth.current_scheme.get() is None
    assert dispatch._secure() is False
    context = auth.current_scheme.set("https")
    try:
        assert dispatch._secure() is True
    finally:
        auth.current_scheme.reset(context)
    context = auth.current_scheme.set("http")
    try:
        assert dispatch._secure() is False
    finally:
        auth.current_scheme.reset(context)


def test_write_succeeds_with_secure_ssl_redirect(settings, token, root_page):
    """Creates must survive SECURE_SSL_REDIRECT (issue #5).

    The in-process test client defaults to plain http, so with
    ``SECURE_SSL_REDIRECT=True`` SecurityMiddleware 301s the POST and the
    client re-issues it as GET (the method is preserved only for 307/308) —
    the create silently returns the collection list and saves nothing.
    Dispatch must replicate the outer request's scheme via
    ``auth.current_scheme``.
    """

    settings.SECURE_SSL_REDIRECT = True
    settings.ALLOWED_HOSTS = ["*"]
    context = auth.current_scheme.set("https")
    try:
        data = call_operation(
            "pages_create",
            body={
                "meta": {
                    "type": "wagtail_mcp_test.ContentPage",
                    "parent_id": root_page.pk,
                },
                "title": "Redirect-proof",
            },
            token=token,
        )
    finally:
        auth.current_scheme.reset(context)
    assert data["title"] == "Redirect-proof"
    assert "items" not in data  # a list payload means POST degraded to GET
    assert ContentPage.objects.filter(title="Redirect-proof").exists()


def test_update_succeeds_with_secure_ssl_redirect(settings, token, root_page):
    """PATCH must survive SECURE_SSL_REDIRECT (issue #5, update variant)."""

    child = ContentPage(title="Before redirect", slug="before-redirect")
    root_page.add_child(instance=child)
    settings.SECURE_SSL_REDIRECT = True
    settings.ALLOWED_HOSTS = ["*"]
    context = auth.current_scheme.set("https")
    try:
        data = call_operation(
            "pages_update",
            path_params={"page_id": child.pk},
            body={
                "meta": {"type": "wagtail_mcp_test.ContentPage"},
                "title": "After redirect",
            },
            token=token,
        )
    finally:
        auth.current_scheme.reset(context)
    assert data["title"] == "After redirect"
    # In Wagtail 8 the base Page carries DraftStateMixin, so editing a live
    # page stores the change as a draft revision and leaves the live row
    # untouched until publish. The new revision is the durable proof the
    # PATCH reached the handler (degraded to GET, there would be no revision
    # and the detail title would still be the old one).
    revision = child.revisions.order_by("pk").last()
    assert revision is not None
    assert revision.as_object().title == "After redirect"


def test_pages_find_follows_redirect(root_page, token):
    # pages_find returns a 302 to the page-detail URL (like any HTTP client).
    hostname = "example.test"
    Site.objects.create(hostname=hostname, root_page=root_page, is_default_site=True)
    child = ContentPage(title="Found target", slug="found-target")
    root_page.add_child(instance=child)
    child.save_revision().publish()  # a published page is required for a live detail_url
    data = call_operation(
        "pages_find",
        query={"html_path": "found-target/", "site": hostname},
        token=token,
    )
    assert data["id"] == child.pk
    assert data["meta"]["slug"] == "found-target"


def test_pages_delete_returns_none(root_page, token):
    # pages_delete responds 204 with an empty body → call_operation returns None.
    child = ContentPage(title="To delete", slug="to-delete")
    root_page.add_child(instance=child)
    result = call_operation(
        "pages_delete", path_params={"page_id": child.pk}, token=token
    )
    assert result is None


def test_missing_path_param_raises_clean_apierror(token):
    # pages_detail requires {page_id} in its path template.
    with pytest.raises(APIError) as exc:
        call_operation("pages_detail", token=token)
    assert exc.value.status == 400
    assert "page_id" in exc.value.problem["detail"]


def test_malformed_path_template_raises_clean_apierror():
    # A path template with an unnamed field ("{}") raises IndexError from
    # str.format — it must surface as a clean APIError, not a raw exception.
    with mock.patch.object(
        dispatch, "operation_map", return_value={"broken": ("get", "/api/v3/pages/{}")}
    ):
        with pytest.raises(APIError) as exc:
            call_operation("broken")
    assert exc.value.status == 500
    assert "malformed" in exc.value.problem["detail"]


def test_invalid_path_template_raises_clean_apierror():
    # A template with a malformed format spec (nested braces) raises ValueError
    # from str.format — caught and surfaced as an APIError naming the problem.
    with mock.patch.object(
        dispatch,
        "operation_map",
        return_value={"broken": ("get", "/api/v3/pages/{page{{id}")},
    ):
        with pytest.raises(APIError) as exc:
            call_operation("broken", path_params={"page_id": 1})
    assert exc.value.status == 500
    assert "malformed" in exc.value.problem["detail"]


def test_body_with_form_raises_clean_apierror(token):
    with pytest.raises(APIError) as exc:
        call_operation(
            "pages_create",
            body={"meta": {"type": "x"}},
            form={"title": "y"},
            token=token,
        )
    assert exc.value.status == 400
    assert "not both" in exc.value.problem["detail"]


class FakeResponse:
    """Minimal stand-in for ninja.testing.NinjaResponse."""

    def __init__(self, *, status_code, content=None):
        self.status_code = status_code
        self.content = content if content is not None else b""

    def json(self):
        return json_module.loads(self.content if self.content else "{}")


class FakeClient:
    """Records the request it is asked to make and returns a fixed response."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(
        self,
        method,
        path,
        data=None,
        json=None,
        query_params=None,
        headers=None,
        FILES=None,
        host=None,
        port=None,
        secure=None,
    ):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "query_params": query_params,
                "headers": headers or {},
                "host": host,
                "port": port,
                "secure": secure,
            }
        )
        return self.response


def test_non_envelope_5xx_normalized():
    # A 5xx that is not problem+json must surface as a normalized "Unexpected
    # response" APIError rather than crash parsing the body. These tests warm
    # the operation_map cache via the real client first, then swap in the fake.
    operation_map()  # warm cache so call_operation does not hit openapi()
    fake = FakeClient(FakeResponse(status_code=500, content=b"Internal Server Error"))
    with mock.patch.object(dispatch, "_client", return_value=fake):
        with pytest.raises(APIError) as exc:
            call_operation("whoami")
    assert exc.value.status == 500
    assert exc.value.problem["title"] == "Unexpected response"


def test_query_none_values_dropped():
    operation_map()  # warm cache
    fake = FakeClient(FakeResponse(status_code=200, content=b"{}"))
    with mock.patch.object(dispatch, "_client", return_value=fake):
        call_operation("sites_list", query={"limit": 20, "offset": None})
    sent = fake.calls[0]["query_params"]
    assert sent == {"limit": 20}
    assert "offset" not in sent


def test_empty_response_returns_none():
    operation_map()  # warm cache
    fake = FakeClient(FakeResponse(status_code=204, content=b""))
    with mock.patch.object(dispatch, "_client", return_value=fake):
        # pages_actions_unpublish returns an empty body; supply its path param
        # so the request actually fires and the 204 branch is exercised.
        result = call_operation("pages_actions_unpublish", path_params={"page_id": 1})
    assert result is None


def test_no_token_omits_authorization_header():
    # With neither token nor current_token set, we must not send "Bearer None".
    operation_map()  # warm cache
    fake = FakeClient(FakeResponse(status_code=200, content=b"{}"))
    with mock.patch.object(dispatch, "_client", return_value=fake):
        call_operation("sites_list", query={"limit": 5})
    sent_headers = fake.calls[0]["headers"]
    assert "Authorization" not in sent_headers


def test_clear_caches_invalidates_all():
    # Must run after the fake-client tests so the operation_map cache is warm
    # and a fresh openapi() fetch is observable. Keeping it last avoids
    # disturbing earlier tests' shared cache.
    first_schema = openapi()
    assert openapi() is first_schema
    first_ops = operation_map()
    assert operation_map() is first_ops
    clear_caches()
    assert openapi() is not first_schema
    assert operation_map() is not first_ops
    assert operation_map()["whoami"] == ("get", "/api/v3/whoami/")
    # Leave a warm cache behind for any trailing collection needs.
    operation_map()


def test_host_forwarding_controls_absolute_urls(token, settings, root_page):
    """Forwarding the caller's Host shapes absolute API URLs (no testserver).

    When ``WAGTAILAPI_BASE_URL`` is unset, ``get_base_url`` falls back to
    ``Site.find_for_request(request)``, which reads the request's Host. The
    dispatch layer must forward the MCP request's real host (via
    ``auth.current_host``) so absolute ``detail_url``/``html_url`` resolve to the
    caller rather than Django's hardcoded ``testserver`` host.
    """

    settings.WAGTAILAPI_BASE_URL = None
    settings.ALLOWED_HOSTS = ["*"]
    cms_root = ContentPage(title="cms", slug="cms")
    root_page.add_child(instance=cms_root)
    other_root = ContentPage(title="other", slug="other")
    root_page.add_child(instance=other_root)
    Site.objects.create(
        hostname="cms.example.com", root_page=cms_root, is_default_site=False
    )
    Site.objects.create(
        hostname="other.example.com", root_page=other_root, is_default_site=True
    )
    page = ContentPage(title="T", slug="t")
    cms_root.add_child(instance=page)
    page.save_revision().publish()

    token_var = auth.current_token.set(token)
    try:
        auth.current_host.set("cms.example.com")
        result = call_operation(
            "pages_detail", path_params={"page_id": page.pk}, query={"version": "live"}
        )
        detail_url = result["meta"]["detail_url"]
        assert "cms.example.com" in detail_url
        assert "testserver" not in detail_url
    finally:
        auth.current_token.reset(token_var)
        auth.current_host.set(None)
