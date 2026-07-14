# Configuration System

## What It Does
Loads and merges BBAgent settings from `~/.bbagent/config.yaml` with built-in defaults. Auto-detects LLM provider from the `base_url` when `provider` is set to `"auto"`.

## How It Works

### Config File Location
```
~/.bbagent/config.yaml
```

### Built-in Defaults (`DEFAULT_CONFIG`)
```yaml
model: ""                    # Auto-resolved per provider
provider: "auto"             # auto, openai, ollama, openrouter, google, nvidia, custom
base_url: ""                 # Auto-detected when empty
max_iterations: 30
max_tokens: 8192
context_limit: 128000
subagent_max_iterations: 15
compress_at_pct: 0.50
tools:
  core: true
  memory: true
  skills: true
self_review:
  enabled: true
  interval: 3                # Every N turns
  max_tokens: 1000
```

### Provider Auto-Detection
When `provider: "auto"` is set, `detect_provider()` inspects the `base_url`:

| URL Pattern            | Detected Provider |
|------------------------|-------------------|
| `api.openai.com`       | openai            |
| `localhost:11434`      | ollama            |
| `openrouter.ai`        | openrouter        |
| `googleapis.com`       | google            |
| `nvidia.com`           | nvidia            |

### API Key Resolution
Keys are read from environment variables (never from config.yaml for security):
- **OpenAI**: `OPENAI_API_KEY`
- **Ollama**: `OLLAMA_API_KEY` (defaults to `"ollama"` if unset — local only)
- **OpenRouter**: `OPENROUTER_API_KEY`
- **Google**: `GOOGLE_API_KEY`
- **NVIDIA**: `NVIDIA_API_KEY`
- **Custom**: `CUSTOM_API_KEY`

### Default Models Per Provider
| Provider   | Default Model               |
|------------|-----------------------------|
| openai     | gpt-4o                      |
| ollama     | llama3.2                    |
| openrouter | anthropic/claude-3.5-sonnet |
| google     | gemini-2.0-flash            |
| nvidia     | meta/llama-3.1-70b-instruct |

### Config Loading Order
1. `DEFAULT_CONFIG` (hardcoded dict)
2. `~/.bbagent/config.yaml` (file overrides deep-merge into defaults)
3. CLI arguments (e.g. `--model`, `--provider`) override config values
4. Environment variables (API keys only)
