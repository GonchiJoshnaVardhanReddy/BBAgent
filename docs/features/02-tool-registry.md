# Tool Registry

## What It Does
Central registry where tools self-register at import time. The registry stores tool schemas (sent to the LLM on every API call) and dispatches tool calls to the correct handler.

## How It Works

### Architecture
```python
ToolRegistry
  ├── _tools: Dict[str, ToolEntry]
  │     Each ToolEntry stores:
  │       - name        (unique tool name)
  │       - toolset     (grouping, e.g. "core", "mcp-github")
  │       - schema      (OpenAI function-calling format)
  │       - handler     (callable that takes args dict, returns JSON str)
  │       - check_fn    (optional! returns bool — gates tool availability)
  │
  ├── register(name, toolset, schema, handler, check_fn=None)
  ├── get_schemas(tool_names)  → OpenAI-format list for API calls
  ├── dispatch(name, args)     → calls handler, returns JSON str
  ├── get_tool_names()         → list all registered tools
  └── get_toolset_for(name)    → returns toolset string
```

### Self-Registration Pattern
Each tool file registers itself at module load:
```python
registry.register(
    "terminal", "core", {
        "name": "terminal",
        "description": "Run a shell command.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["command"],
        },
    }, _tool_terminal, _check_terminal,
)
```

### Tool Availability Gates
The optional `check_fn` controls whether a tool appears in the schema list sent to the LLM:
- `_check_terminal()` → always returns True
- `_check_file()` → always returns True
- MCP tools → available if the MCP server connected successfully

### Why Use a Registry?
The registry pattern decouples **tool definition** from **tool discovery**. Tools can live anywhere (built-in, plugin, MCP server) and the agent loop doesn't need to know where they come from — it only calls `registry.get_schemas()` and `registry.dispatch()`.
