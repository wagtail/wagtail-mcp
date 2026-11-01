import functools

from mcp.server.mcpserver import MCPServer


@functools.cache
def get_server() -> MCPServer:
    """Return the process-wide MCP server singleton (tools registered once)."""
    server = MCPServer(name="wagtail-mcp")
    from wagtail_mcp.tools import register_all

    register_all(server)
    # The view cannot serve listen streams; unregistered, discover stops offering them.
    server._lowlevel_server._request_handlers.pop("subscriptions/listen", None)
    return server
