# Interactive CLI

## What It Does
Provides a simple interactive command-line interface for chatting with the agent in real-time. Also supports one-shot prompts for scripting.

## How It Works

### Interactive Mode
```
$ python bbagent.py -i

==================================================
  BBAgent — Bug Bounty AI Agent
  Session: 20260713_143022_a1b2c3
  Model: gpt-4o
  Tools: 9 loaded
==================================================

▶ Recon example.com
```

### One-Shot Mode
```bash
python bbagent.py "Recon example.com"
python bbagent.py --model gpt-4o "Scan target.com for open ports"
```

### CLI Arguments
| Flag | Description |
|------|-------------|
| `prompt` | Prompt to run (non-interactive) |
| `-i`, `--interactive` | Interactive mode |
| `--model MODEL` | Model name override |
| `--provider PROVIDER` | Provider override |
| `--base-url URL` | API base URL override |
| `--max-iterations N` | Override max iterations |
| `--no-self-review` | Disable self-review |
| `--self-review-interval N` | Override review interval |
| `--uninstall` | Remove BBAgent and all its data |

### Startup Output
On startup, BBAgent prints:
- Provider and model (e.g. `OPENAI: gpt-4o @ https://api.openai.com/v1`)
- Self-review status (ON/OFF with interval)
- MCP servers connected (if any)
- Number of tools loaded

### Exit Commands
In interactive mode:
- Type `exit`, `quit`, `/exit`, or `/quit` to stop
- Press Ctrl+C or Ctrl+D

### Session Persistence
Every conversation is saved to `~/.bbagent/sessions/<session_id>.json`. This means you can inspect past sessions even after the agent exits.
