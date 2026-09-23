from django.contrib import admin
from django.urls import include, path
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.api.v3.urls import api as api_v3
from wagtail.documents import urls as wagtaildocs_urls


urlpatterns = [
    path("django-admin/", admin.site.urls),
    # Admin agent AG-UI endpoint (own staff gate; see docs/admin-agent.md).
    path("admin/wagtail_mcp/agent/api/", include("wagtail_mcp.agent.urls")),
    path("admin/", include(wagtailadmin_urls)),
    path("api/v3/", api_v3.urls),
    path("mcp/", include("wagtail_mcp.urls")),
    path("documents/", include(wagtaildocs_urls)),
    path("", include(wagtail_urls)),
]
