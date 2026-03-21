"""MCPDB — MCP server for natural language database exploration and analysis."""

__version__ = "5.4.0"


def jupyterserverproxy() -> dict:
    return {
        "command": [
            "mcpdb",
            "web",
            "--no-browser",
            "--no-cache",
            "--root-path",
            "/mcpdb",
            "--port",
            "{port}",
        ],
    }
