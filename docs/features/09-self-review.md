# Self-Review System (Autonomous Learning)

## What It Does
After each conversation turn, BBAgent makes a quick follow-up LLM call to review the exchange and extract anything worth saving to persistent memory or as a reusable skill. This is the agent's "learning" mechanism.

## How It Works

### Trigger Conditions
- `self_review.enabled` must be `true` (default)
- Assistant response must be ≥20 characters
- Interval throttle: runs every `interval` turns (default: every 3rd turn, `interval: 3`)
  - If `interval: 0`, runs on every turn

### Review Prompt
The agent sends its last 4 messages plus this prompt:

> "Review the exchange above. Is there anything worth remembering for future sessions? Reply with a JSON object ONLY."

The response is parsed for three keys:

```json
{
  "memory_entries": [
    "nmap -sV -sC is good for initial scan",
    "Apache 2.4.49 is vulnerable to path traversal CVE-2021-41773"
  ],
  "user_entries": [
    "prefers concise answers",
    "works on bug bounty programs"
  ],
  "skill_to_create": "subdomain-enum",
  "skill_content": "---\nname: subdomain-enum\n..."
}
```

### What Gets Saved
- **Memory entries**: Facts, techniques, environment details → appended to `MEMORY.md`
- **User entries**: User preferences, style, identity → appended to `USER.md`
- **Skill**: If the review detects a reusable technique, it creates a new skill file in `~/.bbagent/skills/<name>/SKILL.md`

### Best-Effort Design
The review call is **best-effort** — it runs in the normal flow after the final response. If it fails (JSON parse error, API error, etc.), the exception is silently caught. The agent never crashes on a failed review.

### Configuration
```yaml
self_review:
  enabled: true      # On/off
  interval: 3        # Run every N turns (0 = every turn)
  max_tokens: 1000   # Max tokens for review response
```

### CLI Flags
- `--no-self-review` — Disable self-review
- `--self-review-interval N` — Override the interval
