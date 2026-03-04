"""MCPDB CLI entry point."""

from __future__ import annotations

import sys

from mcpdb import __version__
from mcpdb.config import load_config
from mcpdb.logging import setup_logging


def main() -> None:
    logger = setup_logging()
    config = load_config()

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        logger.info("mcpdb v%s starting (transport=%s)", __version__, config.server.transport)
        import asyncio
        from mcpdb.mcp.server import run_stdio_server
        asyncio.run(run_stdio_server(config))
    else:
        print(f"mcpdb v{__version__}")


if __name__ == "__main__":
    main()
