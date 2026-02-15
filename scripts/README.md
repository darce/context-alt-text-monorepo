# Monorepo Scripts

Cross-project scripts for the monorepo. App-specific scripts live under each app's own `scripts/` directory.

## Structure

```
scripts/
└── mcp/
    ├── mcp-server.sh       # MCP server launch script
    └── unified_server.py   # Unified MCP server for all codebases
```

## mcp/

The MCP (Model Context Protocol) server exposes codebase tools to coding agents. Start it via `mcp/mcp-server.sh`.
