# SOUL.md & System Prompt Builder

## What It Does
Defines the agent's identity and role. The agent can have a SOUL.md file that replaces the default identity, or use the built-in bug bounty hunter prompt.

## Components

### 1. SOUL.md
If `~/.bbagent/SOUL.md` (or `soul.md`) exists, it replaces the default identity prompt entirely. This lets you customize the agent's role:

```markdown
# Super Recon Agent

I am a specialized reconnaissance agent. My sole purpose is to:
1. Find subdomains
2. Map attack surface
3. Collect technology fingerprints

I do NOT test exploits or make hypotheses. I only collect data.
```

### 2. Default Identity
The built-in `DEFAULT_IDENTITY` prompt defines a **4-phase bug bounty workflow**:

**Phase 1: Reconnaissance**
Use `terminal` and `web_search` to gather DNS records, subdomains, ports, web directories, tech stack, and JS endpoints. Save data with `write_file`.

**Phase 2: Hypothesis**
Analyze recon data and write 1-3 testable hypotheses (e.g. "Apache 2.4.49 → CVE-2021-41773").

**Phase 3: Test**
For each hypothesis, run the exploit/payload via `terminal`. If a test fails, analyze why and revise the hypothesis. If it succeeds, save the finding.

**Phase 4: Report**
Write findings with target, vulnerability type, reproduction steps, evidence, and remediation recommendation.

### 3. System Prompt Assembly
```python
def build_system_prompt(memory_context, skills_list, mem_block, user_block):
    parts = []
    
    # 1. SOUL.md (if it exists) or DEFAULT_IDENTITY
    parts.append(soul_or_default)
    
    # 2. Available skills list
    parts.append(f"## Loadable Skills\n\nAvailable skills:\n{skills_list}")
    
    # 3. Bounty memory context (recent findings + learnings)
    if memory_context: parts.append(memory_block)
    
    # 4. Persistent memory snapshot (MEMORY.md)
    if mem_block: parts.append(mem_block)
    
    # 5. User profile snapshot (USER.md)
    if user_block: parts.append(user_block)
    
    return "\n\n".join(parts)
```

### Key Rule
The system prompt is built **once per session** and cached. This preserves LLM prefix caching — the provider only processes the prompt on the first turn, saving cost on all subsequent turns.
