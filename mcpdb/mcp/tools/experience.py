"""Experience MCP tools — manage and query the experience system."""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import TextContent, Tool

from mcpdb.sources.registry import SourceRegistry

logger = logging.getLogger("mcpdb.mcp.tools.experience")


def get_experience_tools() -> list[Tool]:
    """Return experience management tool definitions."""
    return [
        Tool(
            name="get_experience_stats",
            description="Get statistics about the experience system (cache hits, stored patterns, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID to get stats for (optional, all sources if omitted)",
                    },
                },
            },
        ),
        Tool(
            name="list_cached_queries",
            description="List cached queries for a source.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID to list cached queries for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of queries to return",
                        "default": 20,
                    },
                },
                "required": ["source_id"],
            },
        ),
        Tool(
            name="invalidate_cache_entry",
            description="Invalidate a specific cached query response.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID",
                    },
                    "question": {
                        "type": "string",
                        "description": "The question to invalidate the cache for",
                    },
                },
                "required": ["source_id", "question"],
            },
        ),
        Tool(
            name="clear_experience",
            description="Clear all experience data for a source.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID to clear experience for",
                    },
                },
                "required": ["source_id"],
            },
        ),
        Tool(
            name="vote_response",
            description="Vote on a response quality (positive or negative). Negative votes invalidate the cache.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source ID",
                    },
                    "question": {
                        "type": "string",
                        "description": "The question that was answered",
                    },
                    "vote": {
                        "type": "string",
                        "enum": ["up", "down"],
                        "description": "Vote direction",
                    },
                },
                "required": ["source_id", "question", "vote"],
            },
        ),
    ]


def handle_experience_tool(
    name: str,
    args: dict[str, Any],
    registry: SourceRegistry,
    experience_cache: Any = None,
) -> list[TextContent]:
    """Handle experience tool calls."""
    if experience_cache is None:
        return [TextContent(type="text", text="Experience system is not enabled.")]

    if name == "get_experience_stats":
        return _get_stats(args, registry, experience_cache)
    elif name == "list_cached_queries":
        return _list_cached(args, registry, experience_cache)
    elif name == "invalidate_cache_entry":
        return _invalidate(args, registry, experience_cache)
    elif name == "clear_experience":
        return _clear(args, registry, experience_cache)
    elif name == "vote_response":
        return _vote(args, registry, experience_cache)

    return [TextContent(type="text", text=f"Unknown experience tool: {name}")]


def _get_stats(
    args: dict[str, Any],
    registry: SourceRegistry,
    cache: Any,
) -> list[TextContent]:
    """Get experience statistics."""
    source_id = args.get("source_id")

    if source_id:
        meta = registry.get_metadata(source_id)
        if meta is None:
            return [TextContent(type="text", text=f"Source not found: {source_id}")]

        from mcpdb.experience.fingerprint import fingerprint_source
        fp = fingerprint_source(meta)
        stats = cache._store.get_stats(fp)
        lines = [
            f"Experience stats for {source_id}:",
            f"  Total records: {stats['total_records']}",
            f"  Successes: {stats['successes']}",
            f"  Failures: {stats['failures']}",
        ]
    else:
        stats = cache.get_stats()
        lines = [
            "Experience system stats:",
            f"  Memory cache: {stats['memory_entries']}/{stats['memory_max']}",
            f"  Disk sources: {stats['disk_sources']}",
            f"  Disk successes: {stats['disk_total_successes']}",
        ]

    return [TextContent(type="text", text="\n".join(lines))]


def _list_cached(
    args: dict[str, Any],
    registry: SourceRegistry,
    cache: Any,
) -> list[TextContent]:
    """List cached queries for a source."""
    source_id = args["source_id"]
    limit = args.get("limit", 20)

    meta = registry.get_metadata(source_id)
    if meta is None:
        return [TextContent(type="text", text=f"Source not found: {source_id}")]

    from mcpdb.experience.fingerprint import fingerprint_source
    fp = fingerprint_source(meta)
    successes = cache._store.get_successes(fp)

    if not successes:
        return [TextContent(type="text", text=f"No cached queries for {source_id}.")]

    # Sort by timestamp (newest first)
    successes.sort(key=lambda r: r.timestamp, reverse=True)
    successes = successes[:limit]

    lines = [f"Cached queries for {source_id} ({len(successes)} shown):"]
    for i, rec in enumerate(successes, 1):
        mode = rec.query_mode
        preview = rec.response[:80].replace("\n", " ")
        lines.append(f"  {i}. [{mode}] {rec.question}")
        lines.append(f"     → {preview}...")

    return [TextContent(type="text", text="\n".join(lines))]


def _invalidate(
    args: dict[str, Any],
    registry: SourceRegistry,
    cache: Any,
) -> list[TextContent]:
    """Invalidate a specific cache entry."""
    source_id = args["source_id"]
    question = args["question"]

    meta = registry.get_metadata(source_id)
    if meta is None:
        return [TextContent(type="text", text=f"Source not found: {source_id}")]

    cache.invalidate(question, meta)
    return [TextContent(type="text", text=f"Cache entry invalidated for: {question}")]


def _clear(
    args: dict[str, Any],
    registry: SourceRegistry,
    cache: Any,
) -> list[TextContent]:
    """Clear all experience data for a source."""
    source_id = args["source_id"]

    meta = registry.get_metadata(source_id)
    if meta is None:
        return [TextContent(type="text", text=f"Source not found: {source_id}")]

    cache.clear_source(meta)
    return [TextContent(type="text", text=f"All experience data cleared for {source_id}.")]


def _vote(
    args: dict[str, Any],
    registry: SourceRegistry,
    cache: Any,
) -> list[TextContent]:
    """Vote on a response."""
    source_id = args["source_id"]
    question = args["question"]
    vote = args["vote"]

    meta = registry.get_metadata(source_id)
    if meta is None:
        return [TextContent(type="text", text=f"Source not found: {source_id}")]

    if vote == "down":
        cache.invalidate(question, meta)
        return [TextContent(type="text", text="Negative vote recorded. Cache entry invalidated.")]
    else:
        return [TextContent(type="text", text="Positive vote recorded.")]
