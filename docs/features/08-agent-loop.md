# Agent Loop

## What It Does
The core conversation loop that drives all agent behavior. For every user message, it repeatedly calls the LLM, processes tool calls, and returns when the LLM provides a final text response.

## How It Works

### Loop Flow
```
User message → Build system prompt (cached) → LLM call with tools
     │
     ├── Tool call? → Execute tool → Append result → Loop
     │
     └── Text response? → Save session → Background review → Return
```

### Pseudocode
```python
def run(user_message):
    # Build system prompt once per session (cached for prompt caching)
    if not cached_system_prompt:
        rebuild_system_prompt()
    
    messages.append({"role": "user", "content": user_message})
    
    # Maybe compress old messages if context is full
    maybe_compress_context()
    
    for iteration in range(max_iterations):
        response = llm.chat(messages, tools=tool_schemas)
        
        if response.tool_calls:
            for call in response.tool_calls:
                result = registry.dispatch(call.name, call.args)
                messages.append(tool_result)
        else:
            # Final answer - save session, run review, return
            save_session()
            background_review()
            return response.text
    
    return "Max iterations reached"
```

### Key Design Decisions

**1. Cached System Prompt**
The system prompt is built once per session and reused for every turn. This keeps LLM prefix caches warm — the provider only processes the system prompt once. Only rebuilt on context compression.

**2. One Retry on API Failure**
If the API call fails, it retries once after a 2-second sleep. If that fails too, it saves the session and returns an error message. Never loses conversation state.

**3. Iteration Limit**
`max_iterations` (default 30) prevents runaway tool-calling loops. The agent must decide between making another tool call or giving a final answer.

**4. Context Compression**
When the conversation approaches the context limit (~50% threshold), old messages are summarized into a compressed block. Keeps the last 10 messages intact. This is essential for long bug bounty sessions with many tool calls.

### Context Compression Detail
```python
def _maybe_compress_context():
    # Estimate: ~4 chars per token
    if total_chars < context_limit * 0.5:
        return  # No compression needed
    
    # Keep last 10 messages, compress everything before
    summary = "[Earlier context compressed]"
    messages = [compressed_summary] + last_10_messages
```
