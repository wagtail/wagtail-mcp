from django.urls import include, path, reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView
from django.views.i18n import JavaScriptCatalog
from wagtail import hooks
from wagtail.admin.menu import MenuItem

from wagtail_mcp.agent.availability import try_reverse_agent_endpoint


class AgentSetupRequiredView(TemplateView):
    template_name = "wagtail_mcp/admin/agent_page.html"


class AgentMenuItem(MenuItem):
    """Sidebar item, shown only when the AG-UI endpoint is mounted."""

    def is_shown(self, request):
        return try_reverse_agent_endpoint() is not None


@hooks.register("register_admin_urls")
def register_admin_urls():
    urls = [
        path(
            "jsi18n/",
            JavaScriptCatalog.as_view(packages=["wagtail_mcp"]),
            name="javascript_catalog",
        ),
        # The async AG-UI endpoint itself is mounted from the project
        # URLconf; this page degrades to setup instructions until it is.
        path("agent/", AgentSetupRequiredView.as_view(), name="agent_page"),
    ]

    return [
        path(
            "wagtail_mcp/",
            include(
                (urls, "wagtail_mcp"),
                namespace="wagtail_mcp",
            ),
        )
    ]


@hooks.register("register_admin_menu_item")
def register_agent_menu_item():
    return AgentMenuItem(
        _("Agent"),
        reverse("wagtail_mcp:agent_page"),
        icon_name="comment",
        order=900,
    )
