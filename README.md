# BBAgent — Bug Bounty AI Agent

A minimal, self-learning bug bounty hunting AI agent. Runs locally or via cloud LLMs, remembers across sessions, learns from experience, and connects to external tools via MCP.

**Source**: `bbagent.py` — a single file with all features built in.

---

## Quick Start

```bash
# 1. Install dependencies
pip install openai pyyaml

# 2. Set your API key (choose one)
export OPENAI_API_KEY="sk-..."          # OpenAI
# export OPENROUTER_API_KEY="sk-or-..."  # OpenRouter
# export GOOGLE_API_KEY="..."            # Google AI Studio
# export NVIDIA_API_KEY="nvapi-..."      # NVIDIA

# 3. Run interactive mode
python bbagent.py -i
```

**No API key?** If you have [Ollama](https://ollama.ai) running locally, just set `OLLAMA_API_KEY=ollama` and it'll work out of the box.

**Prerequisites:** Python 3.8+, pip. The `web_search` tool also requires `curl`.

---

## Usage

### Interactive mode

```bash
python bbagent.py -i
```

Starts a REPL with slash commands:

| Command | Description |
|---------|-------------|
| `/search <query>` | Search past conversations |
| `/stats` | Show session database stats |
| `/prune` | Force-prune old sessions |
| `/help` | Show all available commands |
| `/clear` | Clear the terminal screen |
| `/exit` or `/quit` | Exit |

### One-shot mode

```bash
python bbagent.py "Recon example.com"
python bbagent.py "Scan target.com for open ports"
```

### CLI options

| Flag | Description |
|------|-------------|
| `-i` | Interactive mode |
| `--model <name>` | LLM model to use (e.g. `gpt-4o`) |
| `--provider <name>` | Provider: openai, ollama, openrouter, google, nvidia |
| `--base-url <url>` | Custom API endpoint URL |
| `--max-iterations <N>` | Max tool-calling iterations |
| `--no-self-review` | Disable background self-review |
| `--self-review-interval <N>` | Run self-review every N turns |
| `--retention <days>` | Set session retention period |
| `--prune-now` | Immediately prune old sessions |
| `--uninstall` | Remove BBAgent and all its data |

---

## Configuration

Edit `config.yaml` (or let the agent auto-detect from environment):

```yaml
provider: auto
model: ""
max_iterations: 30
max_tokens: 8192
context_limit: 128000

session_search:
  prune_days: 90    # auto-prune sessions older than 90 days
```

**API keys** go in environment variables (not config.yaml):

| Provider | Env Variable | Default Endpoint |
|----------|-------------|-----------------|
| OpenAI | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| Ollama | `OLLAMA_API_KEY` | `http://localhost:11434/v1` |
| OpenRouter | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` |
| Google | `GOOGLE_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| NVIDIA | `NVIDIA_API_KEY` | `https://integrate.api.nvidia.com/v1` |
| Custom | `CUSTOM_API_KEY` | Set via `--base-url` or config |

---

## Features

### Built-in Tools

| Tool | Description |
|------|-------------|
| `terminal` | Run shell commands |
| `read_file` | Read files from disk |
| `write_file` | Write content to files |
| `search_files` | Search files by glob pattern |
| `web_search` | Web search via DuckDuckGo (requires `curl`) |
| `skill_view` | Load reusable skill instructions |
| `skill_manage` | Create / list / view skills |
| `memory` | Save/retrieve persistent facts |
| `session_search` | Search past conversations (FTS5) |
| `delegate_task` | Spawn a subagent for parallel work |

### Self-Review & Learning

After each conversation turn, BBAgent makes a background LLM call to extract:
- **Memory entries** — facts and findings to persist across sessions
- **User preferences** — how you like to work
- **Skills** — reusable techniques saved as SKILL.md files

### Session Search (FTS5)

Every conversation is automatically indexed for full-text search:

```
> /search nmap
  Found 3 session(s) for: nmap
```

Uses SQLite FTS5 when available, falls back to LIKE search otherwise.

### Session Pruning

Old sessions are automatically pruned (default: 90 days). Control via:

```bash
python bbagent.py --retention 60    # change to 60 days
python bbagent.py --prune-now       # force prune now
```

Or from interactive mode: `/prune`

### MCP Client

Connect to any MCP (Model Context Protocol) server:

```yaml
# In config.yaml
mcp_servers:
  github:
    command: npx
    args: ["@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "ghp_..."
```

### Delegation

Spawn subagents for parallel work — they get their own tool-calling loop:

- **Single:** `delegate_task(goal="Scan API endpoints")`
- **Background:** `delegate_task(goal="...", background=true)`
- **Batch:** `delegate_task(tasks=[{...}, {...}])`

### Detailed Feature Docs

Deep-dive documentation for each feature is in the `docs/features/` folder:

```
docs/features/
  01-configuration.md   02-tool-registry.md    03-builtin-tools.md
  04-memory-store.md    05-skills-system.md     06-persistent-memory.md
  07-mcp-client.md      08-agent-loop.md        09-self-review.md
  10-delegation.md      11-interactive-cli.md   12-cross-platform-helpers.md
  13-soul-identity.md
```

---

## Data Locations

All data is stored under `~/.bbagent/`:

| Path | Content |
|------|---------|
| `config.yaml` | User configuration |
| `memory.json` | Bounty memory (findings, learnings, targets) |
| `memories/MEMORY.md` | Agent's persistent notes |
| `memories/USER.md` | User profile |
| `skills/<name>/SKILL.md` | Reusable technique skills |
| `sessions/<id>.json` | Saved conversation sessions |
| `SOUL.md` | Custom agent identity (optional) |
| `state.db` | SQLite session search index |

---

## Architecture

```
bbagent.py
├── Configuration       (config.yaml + env vars + auto provider detection)
├── Tool Registry       (self-registering tools -> OpenAI function schemas)
├── Built-in Tools      (terminal, file, web, skills, memory, delegation)
├── MCP Client          (stdio JSON-RPC -> external MCP servers)
├── Memory Store        (~/.bbagent/memory.json)
├── Persistent Memory   (~/.bbagent/memories/MEMORY.md + USER.md)
├── Skills System       (~/.bbagent/skills/<name>/SKILL.md)
├── Session Search      (SQLite FTS5 full-text search)
├── Session Pruning     (auto/manual retention management)
├── Agent Loop          (run -> tool calls -> final response)
├── Self-Review         (post-turn background learning)
├── Delegation          (subagent thread spawning)
└── CLI Entry Point     (argparse + interactive/one-shot modes)
```

---

## Running Tests

```bash
pip install pytest
python -m pytest test_bbagent.py -v
```

All tests pass.

---

## Uninstall

```bash
python bbagent.py --uninstall
```

Removes `~/.bbagent/` and all BBAgent files.
