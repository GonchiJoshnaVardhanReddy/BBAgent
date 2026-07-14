# Persistent Memory (MEMORY.md / USER.md)

## What It Does
Cross-session persistent memory using plain markdown files with `§`-delimited entries. Two files serve different purposes:

- **MEMORY.md** — Agent's notes about the environment, workflows, techniques learned
- **USER.md** — What the agent knows about the user (preferences, communication style, identity)

Both are loaded as a **frozen snapshot** at session start and injected into the system prompt. Mid-session writes update files on disk but NOT the snapshot (preserving prompt caching).

## How It Works

### File Location
```
~/.bbagent/memories/
  ├── MEMORY.md
  └── USER.md
```

### Storage Format
Entries are separated by the `§` delimiter:
```
nmap -sV -sC is good for first pass§Always check login forms for default credentials§§Use nuclei for known CVEs
```

### Character Limits
- MEMORY.md: 2200 chars max
- USER.md: 1375 chars max

These limits prevent the system prompt from growing too large.

### Tool Interface
All operations go through the `memory` tool with `target="memory"` or `target="user"`:

**Single Operations:**
- `{action: "add", target: "memory", content: "entry text"}` — append an entry
- `{action: "replace", target: "memory", old_text: "old part", content: "new text"}` — find and replace by substring
- `{action: "remove", target: "memory", old_text: "text to delete"}` — delete by substring
- `{action: "list", target: "memory"}` — list all entries

**Batch Operations:**
```json
{
  "action": "add",
  "target": "memory",
  "operations": [
    {"action": "add", "content": "New learning"},
    {"action": "remove", "old_text": "old thing"},
    {"action": "replace", "old_text": "bad", "content": "good"}
  ]
}
```

### Safety Features
- **Duplicate detection**: Adding an existing entry is a no-op
- **Match ambiguity check**: If multiple entries match `old_text`, the tool refuses with a hint to be more specific
- **Budget check**: Before any add operation, checks remaining character budget
- **Batch atomicity**: The entire batch passes or fails as a unit
