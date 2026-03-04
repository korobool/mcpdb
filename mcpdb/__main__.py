"""MCPDB CLI entry point."""

from __future__ import annotations

import sys

from mcpdb import __version__
from mcpdb.config import load_config
from mcpdb.logging import setup_logging


USAGE = f"""\
mcpdb v{__version__} — MCP server for natural language database exploration

Usage:
  mcpdb                          Print version
  mcpdb serve                    Start MCP server (stdio, for Claude Desktop)
  mcpdb serve --transport sse    Start MCP server (SSE, for web clients)
  mcpdb serve --port 8765        Start SSE server on custom port
  mcpdb ui                       Start the web UI
  mcpdb ui --port 8080           Start UI on custom port
  mcpdb query <conn> <question>  One-shot query mode
"""


def main() -> None:
    logger = setup_logging()
    config = load_config()

    args = sys.argv[1:]

    if not args:
        print(f"mcpdb v{__version__}")
        return

    command = args[0]

    if command == "serve":
        transport = "stdio"
        port = config.server.port

        i = 1
        while i < len(args):
            if args[i] == "--transport" and i + 1 < len(args):
                transport = args[i + 1]
                i += 2
            elif args[i] == "--port" and i + 1 < len(args):
                port = int(args[i + 1])
                i += 2
            else:
                i += 1

        logger.info("mcpdb v%s starting (transport=%s)", __version__, transport)

        if transport == "stdio":
            import asyncio
            from mcpdb.mcp.server import run_stdio_server
            asyncio.run(run_stdio_server(config))
        elif transport == "sse":
            import asyncio
            from mcpdb.mcp.server import run_sse_server
            try:
                asyncio.run(run_sse_server(config, port=port))
            except AttributeError:
                logger.error("SSE transport not yet implemented in server module")
                sys.exit(1)
        else:
            print(f"Unknown transport: {transport}")
            sys.exit(1)

    elif command == "ui":
        port = 8080
        theme = "dark"

        i = 1
        while i < len(args):
            if args[i] == "--port" and i + 1 < len(args):
                port = int(args[i + 1])
                i += 2
            elif args[i] == "--theme" and i + 1 < len(args):
                theme = args[i + 1]
                i += 2
            else:
                i += 1

        logger.info("mcpdb v%s UI starting on port %d", __version__, port)
        try:
            from mcpdb.ui.app import run_ui
            run_ui(port=port, theme=theme)
        except ImportError:
            print("UI requires NiceGUI. Install with: pip install mcpdb[ui]")
            sys.exit(1)

    elif command == "query":
        if len(args) < 3:
            print("Usage: mcpdb query <connection_string> <question>")
            sys.exit(1)

        connection_string = args[1]
        question = " ".join(args[2:])
        _oneshot_query(connection_string, question, config, logger)

    elif command in ("--help", "-h", "help"):
        print(USAGE)

    elif command in ("--version", "-V"):
        print(f"mcpdb v{__version__}")

    else:
        print(f"Unknown command: {command}")
        print(USAGE)
        sys.exit(1)


def _oneshot_query(connection_string: str, question: str, config, logger) -> None:
    """Run a one-shot query and print the result."""
    import asyncio

    async def run():
        from mcpdb.sources.database.source import DatabaseSource
        from mcpdb.sources.registry import SourceRegistry
        from mcpdb.agent.graph import run_agent
        from mcpdb.llm.provider import AnthropicProvider

        registry = SourceRegistry()
        try:
            source = DatabaseSource(connection_string)
            registry.add_source(source)
            logger.info("Connected to %s", connection_string)

            llm = AnthropicProvider(
                model=config.llm.reasoning.model,
                api_key=config.llm.reasoning.api_key,
            )

            state = await run_agent(question, registry, llm)
            response = state.get("response", "No response generated.")
            print(response)
        finally:
            registry.close_all()

    asyncio.run(run())


if __name__ == "__main__":
    main()
