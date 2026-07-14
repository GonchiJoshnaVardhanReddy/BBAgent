# Memory Store

## What It Does
JSON-backed long-term memory that survives across agent sessions. Stores three types of data: targets (hosts), findings (vulnerabilities discovered), and learnings (techniques learned).

## How It Works

### Data Location
```
~/.bbagent/memory.json
```

### Data Structure
```json
{
  "targets": {
    "example.com": {
      "subdomains": ["admin.example.com"],
      "ports": ["80", "443"],
      "last_updated": "2026-07-13T..."
    }
  },
  "findings": [
    {
      "type": "vuln",
      "target": "example.com",
      "summary": "XSS in login form",
      "timestamp": "2026-07-13T..."
    }
  ],
  "learnings": [
    {
      "text": "Always check for CVE-2024-... when seeing Apache 2.4.49",
      "timestamp": "2026-07-13T..."
    }
  ]
}
```

### Key Methods
- `add_target(host, data)` — update target info (merge + timestamp)
- `add_finding(finding)` — append a vulnerability finding
- `add_learning(learning)` — save a technique for future use
- `get_context()` — returns a formatted string for system prompt injection (last 5 findings + last 3 learnings)

### Upgrade Path
When you have 100+ findings, the current JSON approach still works fine for fast reads. If you need semantic search, consider adding SQLite with FTS5 (like Hermes does) or a vector DB.
