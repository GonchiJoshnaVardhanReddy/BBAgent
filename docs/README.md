# BBAgent — Bug Bounty AI Agent

A minimal, self-learning bug bounty hunting AI agent built on Hermes Agent's core architecture. Runs locally or via cloud LLMs, remembers across sessions, learns from experience, and connects to external tools via MCP.

**Source**: `bbagent.py` — a single file, ~1400 lines.

---

## Quick Start

```bash
pip install openai pyyaml
export OPENAI_API_KEY="sk-..."
python bbagent.py -i
```

Or use the auto-installer:
```bash
python setup_bbagent.py
python setup_bbagent.py --auto  # Non-interactive
```

---

## Features Overview

| #  | Feature | File |
|----|---------|------|
| 01 | [Configuration System](features/01-configuration.md) | Config loading, provider auto-detection, API key resolution |
| 02 | [Tool Registry](features/02-tool-registry.md) | Central tool registry with self-registration pattern |
| 03 | [Built-in Tools](features/03-builtin-tools.md) | terminal, read/write file, search, web search, skills, memory, delegation |
| 04 | [Memory Store](features/04-memory-store.md) | JSON-backed long-term memory (targets, findings, learnings) |
| 05 | [Skills System](features/05-skills-system.md) | Markdown-based skill files with self-learning |
| 06 | [Persistent Memory](features/06-persistent-memory.md) | MEMORY.md / USER.md cross-session memory |
| 07 | [MCP Client](features/07-mcp-client.md) | Model Context Protocol server integration |
| 08 | [Agent Loop](features/08-agent-loop.md) | Core conversation loop with tool calling |
| 09 | [Self-Review System](features/09-self-review.md) | Autonomous learning from conversations |
| 10 | [Delegation](features/10-delegation.md) | Subagent spawning for parallel work |
| 11 | [Interactive CLI](features/11-interactive-cli.md) | Interactive and one-shot modes |
| 12 | [Cross-platform Helpers](features/12-cross-platform-helpers.md) | Windows/macOS/Linux compatibility |
| 13 | [SOUL.md & System Prompt Builder](features/13-soul-identity.md) | Agent identity and prompt assembly |

---

## CLI Usage

```bash
# Interactive mode
python bbagent.py -i

# One-shot prompt
python bbagent.py "Recon example.com"

# With specific provider
python bbagent.py --provider ollama --model llama3.2 -i

# With custom base URL
python bbagent.py --base-url http://localhost:11434/v1 --model llama3.2

# Disable self-review
python bbagent.py --no-self-review "Scan target"

# Uninstall
python bbagent.py --uninstall
```

## Architecture Overview

```
bbagent.py
├── Configuration       (DEFAULT_CONFIG → ~/.bbagent/config.yaml)
├── Provider Detection  (auto / openai / ollama / openrouter / google / nvidia)
├── Tool Registry       (self-registering tools → OpenAI function schemas)
├── MCP Client          (stdio JSON-RPC → external MCP servers)
├── Memory Store        (~/.bbagent/memory.json)
├── Persistent Memory   (~/.bbagent/memories/MEMORY.md + USER.md)
├── Skills System       (~/.bbagent/skills/<name>/SKILL.md)
├── System Prompt Builder (SOUL.md + identity + memory + skills)
├── Agent Loop          (run → tool calls → final response)
├── Self-Review         (post-turn background learning)
├── Delegation          (subagent thread spawning)
├── Utilities           (safe_print, cross-platform helpers)
└── CLI Entry Point     (main() — argparse + interactive/one-shot mode)
```

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
