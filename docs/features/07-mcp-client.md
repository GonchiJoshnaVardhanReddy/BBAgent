# MCP Client (Model Context Protocol)

## What It Does
Connects to MCP servers via JSON-RPC over stdio. Each MCP server exposes tools that get registered into the tool registry and become available to the agent — just like built-in tools.

## How It Works

### Architecture
```python
MCPClient
  ├── connect() — spawn subprocess, initialize handshake, list tools
  ├── call_tool(name, arguments) — send JSON-RPC request, return result
  ├── get_tool_schemas() — convert MCP tool defs to OpenAI function schemas
  └── disconnect() — terminate the server process
```

### Connection Handshake
1. Spawn MCP server subprocess with configured env vars
2. Send `initialize` JSON-RPC request (protocol v2024-11-05)
3. Send `notifications/initialized` notification
4. Send `tools/list` to discover available tools
5. Register each discovered tool in the global `registry`

### Configured MCP Servers
From `~/.bbagent/config.yaml` under `mcp_servers:`:

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"
```

### Built-in MCP Server Templates
The default config includes commented-out templates for:

| Server | Description | Requires |
|--------|-------------|----------|
| **GitHub** | Repository management, code search, issues, PRs | Node.js + GITHUB_TOKEN |
| **Filesystem** | Sandboxed file read/write in allowed dirs | Node.js |
| **Puppeteer** | Browser automation (navigate, screenshot, click) | Node.js + Chrome |
| **SearXNG** | Privacy-respecting web search via JSON API | Node.js + SearXNG instance |

### Windows Compatibility
- `shutil.which()` resolves `.cmd` files (Node/npx on Windows)
- `select.select()` doesn't support pipes on Windows — falls back to thread-based read timeout
- All env var bridging works cross-platform

### Auto Token Resolution
If a `github` MCP server is configured but the user didn't set `GITHUB_PERSONAL_ACCESS_TOKEN` in the config, the system auto-injects it from `GITHUB_TOKEN` or `GITHUB_PERSONAL_ACCESS_TOKEN` environment variables.
