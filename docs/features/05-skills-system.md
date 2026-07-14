# Skills System

## What It Does
Skills are markdown files that teach the agent how to perform specific tasks. The agent can create new skills from experience, load existing ones, and reuse effective techniques across sessions.

## How It Works

### Skill Location
```
~/.bbagent/skills/
  ├── xss-detection/
  │   └── SKILL.md
  ├── subdomain-enum/
  │   └── SKILL.md
  └── ...
```

### SKILL.md Format
```markdown
---
name: xss-detection
description: Test for XSS vulnerabilities systematically.
version: 1.0
---

# XSS Detection Skill

## When to Use
When testing a web form or URL parameter for XSS.

## Prerequisites
- Target URL and parameter names
- Access to terminal (for curl/payload delivery)

## Procedure
1. Test with `"><script>alert(1)</script>` in each parameter
2. Test with `'><script>alert(1)</script>`
3. Test with event handlers: `<img src=x onerror=alert(1)>`
4. Note any reflection in the response
5. If reflected, try to craft a working payload

## Verification
Confirm alert execution in browser or response reflection.
```

### Tool Commands
- `skill_view(name)` — Load a skill and get its instructions
- `skill_manage(action="create", name, content)` — Create a new skill
- `skill_manage(action="list")` — List all available skills
- `skill_manage(action="view", name)` — View a skill (same as skill_view)

### Self-Learning Integration
The Self-Review system (see feature doc 09) can automatically create skills when it detects a reusable technique during conversation review. Skills created this way appear in `~/.bbagent/skills/` and are available in future sessions.

### Skill Discovery on Startup
On each session start, `build_skills_list()` scans `~/.bbagent/skills/` and reads the `description:` field from each SKILL.md frontmatter. This list is injected into the system prompt so the agent knows what skills are available.
