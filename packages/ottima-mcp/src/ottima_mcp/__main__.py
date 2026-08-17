"""Entrypoint do servidor MCP stdio (`ottima-mcp` no `.mcp.json`, ADR-036)."""

from ottima_mcp.server import mcp


def main() -> None:
    mcp.run()  # default: stdio


if __name__ == "__main__":
    main()
