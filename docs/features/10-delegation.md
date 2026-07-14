# Delegation (Subagent Spawning)

## What It Does
Allows the main agent to spawn a subagent for parallel work — scanning multiple targets, writing reports, processing recon data — while the main agent continues its own work.

## How It Works

### Implementation
`_spawn_subagent()` runs a lightweight completion-only LLM call in a background thread:

```python
def _spawn_subagent(config, goal, context="", timeout=120):
    # Create a new OpenAI client with subagent config
    # (uses parent's API key, model, etc.)
    
    # Run in daemon thread with timeout
    thread = Thread(target=_run_subagent)
    thread.start()
    thread.join(timeout)
    
    if thread.is_alive(): return "timeout error"
    return result
```

### Tool Interface
```json
{
  "goal": "Scan example.com for open ports",
  "context": "Target is a web application, focus on HTTP-related services",
  "timeout": 120
}
```

### Current Limitations
1. **No tools** — the subagent is a simple text completion call. It can't run terminal commands, read files, or use skills. It's a "thinker" agent, not an "actor".
2. **No tool schemas** — the subagent doesn't inherit the parent's tool registry
3. **Timeout controlled** — defaults to 120s, configurable

### Upgrade Path
To give subagents real tools:
- Pass the parent's tool schemas to the subagent
- Implement the same tool-calling loop in the subagent thread
- Use MCP clients for isolated tool access
- Consider Hermes Agent's delegation system for full subagent support
