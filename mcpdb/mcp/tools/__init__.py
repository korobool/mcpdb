"""MCP tool registrations — centralized dispatcher."""

from __future__ import annotations

import logging
from typing import Any, Callable

from mcp.server import Server
from mcp.types import TextContent, Tool

from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.mcp.tools")

# Tool definitions and handlers are collected here
_tool_defs: list[Tool] = []
_tool_handlers: dict[str, Callable] = {}


def register_all_tools(server: Server, registry: SourceRegistry, llm: Any = None) -> None:
    """Register all MCP tools on the server via a single list_tools/call_tool pair."""
    from mcpdb.mcp.tools.session import get_session_tools, handle_session_tool
    from mcpdb.mcp.tools.querying import get_query_tools, handle_query_tool
    from mcpdb.mcp.tools.discovery import get_discovery_tools, handle_discovery_tool
    from mcpdb.mcp.tools.analysis import get_analysis_tools, handle_analysis_tool
    from mcpdb.mcp.tools.control import get_control_tools, handle_control_tool
    from mcpdb.mcp.tools.profiling import get_profiling_tools, handle_profiling_tool
    from mcpdb.mcp.tools.relationships import get_relationship_tools, handle_relationship_tool
    from mcpdb.mcp.tools.excel import get_excel_tools, handle_excel_tool
    from mcpdb.mcp.tools.export import get_export_tools, handle_export_tool
    from mcpdb.mcp.tools.experience import get_experience_tools, handle_experience_tool

    all_tools: list[Tool] = []
    all_tools.extend(get_session_tools())
    all_tools.extend(get_query_tools())
    all_tools.extend(get_discovery_tools())
    all_tools.extend(get_profiling_tools())
    all_tools.extend(get_relationship_tools())
    all_tools.extend(get_excel_tools())
    all_tools.extend(get_analysis_tools())
    all_tools.extend(get_export_tools())
    all_tools.extend(get_experience_tools())
    all_tools.extend(get_control_tools())

    handlers: dict[str, Callable] = {}
    for tool in get_session_tools():
        handlers[tool.name] = lambda args, r=registry: handle_session_tool(args["_name"], args, r)
    for tool in get_query_tools():
        handlers[tool.name] = lambda args, r=registry: handle_query_tool(args["_name"], args, r)
    for tool in get_discovery_tools():
        handlers[tool.name] = lambda args, r=registry: handle_discovery_tool(args["_name"], args, r)
    for tool in get_profiling_tools():
        handlers[tool.name] = lambda args, r=registry: handle_profiling_tool(args["_name"], args, r)
    for tool in get_relationship_tools():
        handlers[tool.name] = lambda args, r=registry: handle_relationship_tool(args["_name"], args, r)
    for tool in get_excel_tools():
        handlers[tool.name] = lambda args, r=registry, l=llm: handle_excel_tool(args["_name"], args, r, l)
    for tool in get_analysis_tools():
        handlers[tool.name] = lambda args, r=registry, l=llm: handle_analysis_tool(args["_name"], args, r, l)
    for tool in get_export_tools():
        handlers[tool.name] = lambda args: handle_export_tool(args["_name"], args)
    for tool in get_experience_tools():
        handlers[tool.name] = lambda args, r=registry: handle_experience_tool(args["_name"], args, r)
    for tool in get_control_tools():
        handlers[tool.name] = lambda args: handle_control_tool(args["_name"], args)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return all_tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        handler = handlers.get(name)
        if handler is None:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
        try:
            arguments["_name"] = name
            return handler(arguments)
        except Exception as e:
            logger.error("Tool %s failed: %s", name, e, exc_info=True)
            return [TextContent(type="text", text=f"Error: {e}")]
