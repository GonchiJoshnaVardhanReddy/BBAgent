# Built-in Tools

## Tool List

### 1. `terminal`
Run shell commands via subprocess.

| Parameter | Type | Description |
|-----------|------|-------------|
| `command` | string | Shell command to run |
| `timeout` | integer | Timeout in seconds (default 60) |

Returns: `{exit_code, output, truncated}`. Output capped at 50K chars.

### 2. `read_file`
Read file contents from disk.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Absolute path to file |
| `max_chars` | integer | Max chars to read (default 20000) |

Returns: `{content, path}`. Supports `~` expansion.

### 3. `write_file`
Write content to a file, creating parent directories as needed.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Absolute path to file |
| `content` | string | File content (creates parent dirs) |

### 4. `search_files`
Search for files matching a glob pattern.

| Parameter | Type | Description |
|-----------|------|-------------|
| `pattern` | string | Glob pattern (e.g. `**/*.txt`) |
| `path` | string | Directory to search (default `.`) |
| `max_results` | integer | Max results (default 50) |

### 5. `web_search`
Search the web via DuckDuckGo HTML scrape (curl-based, no API key needed).

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string | Search query |

Returns extracted text from DuckDuckGo HTML results (5K char limit). Note: this is a fallback approach — for production use, consider the SearXNG MCP server or a dedicated search API.

### 6. `skill_view`
Load a skill by name.

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | string | Skill name (directory under `~/.bbagent/skills/`) |

### 7. `skill_manage`
Create, view, or list skills.

| Parameter | Type | Description |
|-----------|------|-------------|
| `action` | string | `create` | `view` | `list` |
| `name` | string | Skill name |
| `content` | string | Full SKILL.md content (for `create`) |

### 8. `memory`
Save/recall facts across sessions. Two memory systems:

**Persistent Memory** (target: `memory` or `user`):
- `add` — append an entry to MEMORY.md or USER.md
- `replace` — find and replace an entry by substring match
- `remove` — delete an entry by substring match
- `list` — show all entries
- Supports batch operations via `operations: [{action, content, old_text}]`

**Bounty Data** (target: `finding` or `learning`):
- `get` — return recent findings + learnings as context
- `add` — save a finding or learning

### 9. `delegate_task`
Spawn a subagent for parallel work.

| Parameter | Type | Description |
|-----------|------|-------------|
| `goal` | string | Task description |
| `context` | string | Optional background info |
| `timeout` | integer | Max wait in seconds (default 120) |

## Key Design Principle
"Terminal + File over Custom Tool" — instead of writing a dedicated `nmap_tool`, the agent runs `nmap` through the `terminal` tool. This keeps the tool surface small and avoids schema bloat.
