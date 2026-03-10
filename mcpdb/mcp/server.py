"""MCP server setup — tool registration, capability negotiation, transport."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server

from mcpdb import __version__
from mcpdb.config import McpdbConfig, load_config
from mcpdb.experience.service import ExperienceService
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


def create_server(
    config: McpdbConfig | None = None,
    experience_service: ExperienceService | None = None,
    knowledge_manager: Any = None,
) -> tuple[Server, SourceRegistry]:
    """Create and configure the MCP server with all tools."""
    if config is None:
        config = load_config()

    server = Server("mcpdb")
    registry = SourceRegistry()
    llm = create_llm_from_config(config)

    register_all_tools(server, registry, llm=llm, experience_service=experience_service, knowledge_manager=knowledge_manager)
    register_resources(server, registry)
    register_prompts(server, registry)

    logger.info("MCP server created with tools, resources, and prompts registered (LLM: %s/%s)",
                config.llm.reasoning.provider, config.llm.reasoning.model)
    return server, registry


async def run_stdio_server(config: McpdbConfig | None = None) -> None:
    """Run the MCP server with stdio transport."""
    if config is None:
        config = load_config()

    experience_service = ExperienceService(config.experience)

    # Initialize knowledge manager from config
    knowledge_manager = _create_knowledge_from_config(config)

    server, registry = create_server(config, experience_service=experience_service, knowledge_manager=knowledge_manager)
    logger.info("Starting mcpdb v%s (stdio transport)", __version__)

    # Start background quality evaluation worker
    llm = create_llm_from_config(config)
    await experience_service.start(llm)

    init_options = server.create_initialization_options()

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, init_options)
    finally:
        await experience_service.stop()
        registry.close_all()
        logger.info("MCP server shut down")


def _create_knowledge_from_config(config: McpdbConfig) -> Any:
    """Create a KnowledgeManager from config if enabled and directories exist."""
    if not config.knowledge.enabled:
        return None

    import os
    from pathlib import Path

    dirs = [os.path.expanduser(d) for d in config.knowledge.directories]
    for source_id, path in config.knowledge.sources.items():
        dirs.append(os.path.expanduser(path))

    existing = [d for d in dirs if Path(d).exists()]
    if not existing:
        return None

    from mcpdb.knowledge.manager import KnowledgeManager
    from mcpdb.knowledge.file_provider import FileKnowledgeProvider
    from mcpdb.knowledge.embeddings import resolve_embedding_provider

    embed_provider = resolve_embedding_provider(config.knowledge.embedding)
    mgr = KnowledgeManager()
    mgr.add_file_provider(FileKnowledgeProvider(existing, embedding_provider=embed_provider))
    count = mgr.load()

    if count > 0:
        logger.info("Knowledge: %d chunks loaded from %s (embedding=%s)",
                     count, ", ".join(existing), config.knowledge.embedding)
        return mgr
    return None
