"""MCP server setup — tool registration, capability negotiation, transport."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server

from mcpdb import __version__
from mcpdb.config import McpdbConfig, load_config
from mcpdb.llm.factory import create_provider
from mcpdb.llm.provider import LLMProvider
from mcpdb.sources.registry import SourceRegistry
from mcpdb.mcp.tools import register_all_tools
from mcpdb.mcp.resources import register_resources
from mcpdb.mcp.prompts import register_prompts

logger = logging.getLogger("mcpdb.mcp")


def create_llm_from_config(config: McpdbConfig) -> LLMProvider:
    """Create an LLM provider from configuration."""
    llm_cfg = config.llm.reasoning
    return create_provider(llm_cfg.provider, llm_cfg.model, llm_cfg.api_key)


def create_server(config: McpdbConfig | None = None) -> tuple[Server, SourceRegistry]:
    """Create and configure the MCP server with all tools."""
    if config is None:
        config = load_config()

    server = Server("mcpdb")
    registry = SourceRegistry()
    llm = create_llm_from_config(config)

    register_all_tools(server, registry, llm=llm)
    register_resources(server, registry)
    register_prompts(server, registry)

    logger.info("MCP server created with tools, resources, and prompts registered (LLM: %s/%s)",
                config.llm.reasoning.provider, config.llm.reasoning.model)
    return server, registry


async def run_stdio_server(config: McpdbConfig | None = None) -> None:
    """Run the MCP server with stdio transport."""
    if config is None:
        config = load_config()

    server, registry = create_server(config)
    logger.info("Starting mcpdb v%s (stdio transport)", __version__)

    init_options = server.create_initialization_options()

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, init_options)
    finally:
        registry.close_all()
        logger.info("MCP server shut down")
