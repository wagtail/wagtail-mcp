import json

import pytest

from conftest import make_token
from test_protocol import INIT, TOOLS_LIST, post

from wagtail_mcp.limits import (
    SlidingWindowRateLimiter,
    content_length,
    token_key,
)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_limiter_allows_up_to_limit_then_blocks():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(clock=clock)
    assert [limiter.hit("a", 2, 60) for _ in range(2)] == [0, 0]
    assert limiter.hit("a", 2, 60) == pytest.approx(60)


def test_limiter_window_slides():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(clock=clock)
    limiter.hit("a", 1, 10)
    clock.now += 4
    assert limiter.hit("a", 1, 10) == pytest.approx(6)
    clock.now += 6.1
    assert limiter.hit("a", 1, 10) == 0


def test_limiter_keys_are_independent():
    limiter = SlidingWindowRateLimiter(clock=FakeClock())
    assert limiter.hit("a", 1, 60) == 0
    assert limiter.hit("b", 1, 60) == 0
    assert limiter.hit("a", 1, 60) > 0


def test_limiter_drops_idle_keys():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(clock=clock)
    limiter.hit("old", 5, 10)
    clock.now += 11
    limiter.hit("new", 5, 10)
    assert list(limiter._hits) == ["new"]


def test_token_key_is_not_the_token():
    assert "secret-token" not in token_key("secret-token")
    assert token_key("secret-token") == token_key("secret-token")
    assert token_key(None) == "anonymous"


@pytest.mark.parametrize("value", ["", "abc", "-5", None])
def test_content_length_tolerates_bad_values(rf, value):
    request = rf.post("/mcp/")
    request.META["CONTENT_LENGTH"] = value
    assert content_length(request) == 0


@pytest.fixture(autouse=True)
def reset_limiter():
    from wagtail_mcp.limits import rate_limiter

    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.mark.django_db
def test_no_limits_by_default(client, token):
    for _ in range(5):
        assert post(client, INIT, token).status_code == 200


@pytest.mark.django_db
def test_rate_limit_returns_429_with_retry_after(client, token, settings):
    settings.WAGTAIL_MCP = {"rate_limit_requests": 2, "rate_limit_window": 60}
    assert post(client, INIT, token).status_code == 200
    assert post(client, TOOLS_LIST, token).status_code == 200
    response = post(client, TOOLS_LIST, token)
    assert response.status_code == 429
    assert response.json() == {"error": "rate_limited"}
    assert 1 <= int(response["Retry-After"]) <= 60


@pytest.mark.django_db
def test_rate_limit_is_per_token(client, token, settings):
    from django.contrib.auth import get_user_model

    settings.WAGTAIL_MCP = {"rate_limit_requests": 1, "rate_limit_window": 60}
    other = make_token(get_user_model().objects.create_superuser("b", "b@e.com", "pw"))
    assert post(client, INIT, token).status_code == 200
    assert post(client, INIT, token).status_code == 429
    assert post(client, INIT, other).status_code == 200


@pytest.mark.django_db
def test_invalid_tokens_do_not_use_up_a_valid_tokens_allowance(client, token, settings):
    settings.WAGTAIL_MCP = {"rate_limit_requests": 1, "rate_limit_window": 60}
    for _ in range(3):
        assert post(client, INIT, "nope").status_code == 401
    assert post(client, INIT, token).status_code == 200


@pytest.mark.django_db
def test_oversized_body_returns_413(client, token, settings):
    settings.WAGTAIL_MCP = {"max_request_bytes": 100}
    padded = {**INIT, "params": {**INIT["params"], "pad": "x" * 500}}
    response = post(client, padded, token)
    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}


@pytest.mark.django_db
def test_body_within_limit_is_served(client, token, settings):
    settings.WAGTAIL_MCP = {"max_request_bytes": len(json.dumps(INIT)) + 10}
    assert post(client, INIT, token).status_code == 200


@pytest.mark.django_db
def test_oversized_body_rejected_before_auth(client, settings):
    settings.WAGTAIL_MCP = {"max_request_bytes": 10}
    assert post(client, INIT, None).status_code == 413
