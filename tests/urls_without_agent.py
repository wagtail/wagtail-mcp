"""URLconf mirroring wagtail_mcp.test.urls WITHOUT the agent endpoint.

Used by the opt-in gating tests to prove the admin renders (and hides every
agent surface) when a project does not mount ``wagtail_mcp.agent.urls``.
"""

from django.contrib import admin
from django.urls import include, path
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.api.v3.urls import api as api_v3
from wagtail.documents import urls as wagtaildocs_urls


urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("admin/", include(wagtailadmin_urls)),
    path("api/v3/", api_v3.urls),
    path("mcp/", include("wagtail_mcp.urls")),
    path("documents/", include(wagtaildocs_urls)),
    path("", include(wagtail_urls)),
]
