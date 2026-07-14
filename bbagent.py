#!/usr/bin/env python3
"""
bbagent.py — Minimal Bug Bounty AI Agent

A working skeleton based on Hermes Agent's core architecture.
Includes: conversation loop, tool registry, memory, skills, config.

Usage:
    export OPENAI_API_KEY="sk-..."
    python bbagent.py --model "gpt-4o" --provider openai "Recon example.com"
    python bbagent.py -i                          # interactive mode
    python bbagent.py --uninstall                 # remove all BBAgent files

Dependencies: pip install openai pyyaml
"""

import atexit
import json
import logging
import os
import queue
import re
import select
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field

import yaml

# ── Cross-platform helpers ───────────────────────────────────────────────
_EMOJI_MAP = {
    "\U0001f50c": "[plug]",
    "\U0001f5a5\ufe0f": "[pc]",
    "\u26a0\ufe0f": "[!]",
    "\U0001f4a1": "[i]",
    "\U0001f527": "[tool]",
    "\U0001f4dd": "[note]",
    "\U0001f4be": "[save]",
    "\u2705": "[OK]",
    "\u274c": "[X]",
    "\u2b50": "[*]",
}

_STDOUT_SUPPORTS_UNICODE: Optional[bool] = None


def _safe_print(*args, **kw):
    global _STDOUT_SUPPORTS_UNICODE
    text = " ".join(str(a) for a in args)
    if _STDOUT_SUPPORTS_UNICODE is None:
        try:
            "\u2713".encode(sys.stdout.encoding or "utf-8")
            _STDOUT_SUPPORTS_UNICODE = True
        except (UnicodeEncodeError, UnicodeDecodeError):
            _STDOUT_SUPPORTS_UNICODE = False
    if not _STDOUT_SUPPORTS_UNICODE:
        for emoji, repl in _EMOJI_MAP.items():
            text = text.replace(emoji, repl)
        text = text.encode("ascii", "replace").decode("ascii")
    print(text, **kw)


# ── Configuration ──────────────────────────────────────────────────────────
AGENT_HOME = Path.home() / ".bbagent"

DEFAULT_CONFIG = {
    "model": "",
    "provider": "auto",
    "base_url": "",
    "api_key": "",
    "max_iterations": 30,
    "max_tokens": 8192,
    "context_limit": 128000,
    "subagent_max_iterations": 15,
    "compress_at_pct": 0.50,
    "tools": {
        "core": True,
        "memory": True,
        "skills": True,
    },
    "mcp_servers": {},
    "self_review": {
        "enabled": True,
        "interval": 3,
        "max_tokens": 1000,
    },
    "session_search": {
        "prune_days": 90,
    },
}


PROVIDERS = {
    "openai":    ("https://api.openai.com/v1",             "OPENAI_API_KEY"),
    "ollama":    ("http://localhost:11434/v1",              "OLLAMA_API_KEY"),
    "openrouter":("https://openrouter.ai/api/v1",           "OPENROUTER_API_KEY"),
    "google":    ("https://generativelanguage.googleapis.com/v1beta/openai", "GOOGLE_API_KEY"),
    "nvidia":    ("https://integrate.api.nvidia.com/v1",   "NVIDIA_API_KEY"),
    "custom":    ("",                                      "CUSTOM_API_KEY"),
}


def detect_provider(base_url: str) -> str:
    url = base_url.lower().strip()
    if not url or "openai.com" in url:
        return "openai"
    if "localhost:11434" in url or "127.0.0.1:11434" in url or "ollama" in url:
        return "ollama"
    if "openrouter.ai" in url:
        return "openrouter"
    if "googleapis.com" in url or "generativelanguage" in url:
        return "google"
    if "nvidia.com" in url or "api.nvcf" in url:
        return "nvidia"
    return "custom"


def _resolve_api_key(provider: str, explicit_key: str = "") -> str:
    if explicit_key:
        return explicit_key
    _, env_var = PROVIDERS.get(provider, ("", "CUSTOM_API_KEY"))
    key = os.environ.get(env_var, "")
    if not key and provider == "ollama":
        return "ollama"
    return key


def load_config() -> dict:
    path = AGENT_HOME / "config.yaml"
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        with open(path) as f:
            file_cfg = yaml.safe_load(f) or {}
        for k, v in file_cfg.items():
            if isinstance(config.get(k), dict) and isinstance(v, dict):
                config[k].update(v)
            else:
                config[k] = v
    provider = (config.get("provider") or "auto").strip().lower()
    base_url = (config.get("base_url") or "").strip()
    if provider == "custom" and not base_url:
        base_url = os.environ.get("CUSTOM_BASE_URL", "")
        config["base_url"] = base_url
    if provider == "auto":
        provider = detect_provider(base_url)
        config["provider"] = provider
    if not base_url and provider in PROVIDERS:
        config["base_url"] = PROVIDERS[provider][0]
    if not config.get("api_key"):
        config["api_key"] = _resolve_api_key(provider)
    if not config.get("model"):
        model_map = {
            "openai": "gpt-4o",
            "ollama": "llama3.2",
            "openrouter": "anthropic/claude-3.5-sonnet",
            "google": "gemini-2.0-flash",
            "nvidia": "meta/llama-3.1-70b-instruct",
            "custom": "default",
        }
        config["model"] = model_map.get(provider, "gpt-4o")
    mcp_cfg = config.get("mcp_servers", {})
    if mcp_cfg:
        github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
        for srv_name, srv in mcp_cfg.items():
            if not isinstance(srv, dict):
                continue
            srv_env = srv.get("env", {})
            if isinstance(srv_env, dict):
                if "GITHUB_PERSONAL_ACCESS_TOKEN" not in srv_env and "GITHUB_TOKEN" not in srv_env:
                    if github_token and srv_name == "github":
                        srv_env["GITHUB_PERSONAL_ACCESS_TOKEN"] = github_token
                        srv["env"] = srv_env
    return config


# ── Tool Registry ──────────────────────────────────────────────────────────

@dataclass
class ToolEntry:
    name: str
    toolset: str
    schema: dict
    handler: Callable
    check_fn: Optional[Callable] = None
    description: str = ""


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}

    def register(self, name: str, toolset: str, schema: dict,
                 handler: Callable, check_fn: Optional[Callable] = None):
        self._tools[name] = ToolEntry(
            name=name, toolset=toolset, schema=schema,
            handler=handler, check_fn=check_fn,
            description=schema.get("description", ""),
        )

    def get_schemas(self, tool_names: Set[str]) -> list:
        schemas = []
        for name in sorted(tool_names):
            entry = self._tools.get(name)
            if not entry:
                continue
            if entry.check_fn and not entry.check_fn():
                continue
            schemas.append({"type": "function", "function": entry.schema})
        return schemas

    def dispatch(self, name: str, args: dict, **kw) -> str:
        entry = self._tools.get(name)
        if not entry:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            return entry.handler(args, **kw)
        except Exception as e:
            logging.exception("Tool %s failed", name)
            return json.dumps({"error": f"{name}: {e}"})

    def get_tool_names(self) -> List[str]:
        return sorted(self._tools.keys())

    def get_toolset_for(self, name: str) -> Optional[str]:
        entry = self._tools.get(name)
        return entry.toolset if entry else None


registry = ToolRegistry()


# ── Built-in Tools ─────────────────────────────────────────────────────────

def _tool_terminal(args: dict, **kw) -> str:
    command = args.get("command", "").strip()
    if not command:
        return json.dumps({"error": "command is required"})
    timeout = args.get("timeout", 60)
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8",
        )
        output = result.stdout + result.stderr
        return json.dumps({
            "exit_code": result.returncode,
            "output": output[:50000],
            "truncated": len(output) > 50000,
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Command timed out after {timeout}s"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _tool_read_file(args: dict, **kw) -> str:
    path = args.get("path", "")
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return json.dumps({"error": f"File not found: {path}"})
        content = p.read_text(encoding="utf-8", errors="replace")
        max_chars = args.get("max_chars", 20000)
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[...truncated at {max_chars} chars]"
        return json.dumps({"content": content, "path": str(p.resolve())})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _tool_write_file(args: dict, **kw) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return json.dumps({"success": True, "path": str(p.resolve())})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _tool_search_files(args: dict, **kw) -> str:
    pattern = args.get("pattern", "")
    path = args.get("path", ".")
    try:
        p = Path(path).expanduser()
        if not p.is_dir():
            return json.dumps({"error": f"Not a directory: {path}"})
        matches = []
        for f in p.rglob(pattern):
            if f.is_file():
                matches.append(str(f.relative_to(p)))
                if len(matches) >= args.get("max_results", 50):
                    break
        return json.dumps({"matches": matches, "count": len(matches)})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _tool_web_search(args: dict, **kw) -> str:
    import urllib.parse
    query = args.get("query", "")
    if not query:
        return json.dumps({"error": "query is required"})
    try:
        result = subprocess.run(
            ["curl", "-s",
             "-H", "User-Agent: Mozilla/5.0",
             f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"],
            capture_output=True, text=True, timeout=15,
        )
        text = re.sub(r'<[^>]+>', ' ', result.stdout)
        text = re.sub(r'\s+', ' ', text).strip()[:10000]
        return json.dumps({"results": text[:5000]})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _check_terminal() -> bool:
    return True


def _check_file() -> bool:
    return True


registry.register("terminal", "core", {
    "name": "terminal",
    "description": "Run a shell command. Returns stdout+stderr.",
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run"},
            "timeout": {"type": "integer", "description": "Timeout in seconds"},
        },
        "required": ["command"],
    },
}, _tool_terminal, _check_terminal)

registry.register("read_file", "core", {
    "name": "read_file",
    "description": "Read a file from disk.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to file"},
            "max_chars": {"type": "integer", "description": "Max chars to read"},
        },
        "required": ["path"],
    },
}, _tool_read_file, _check_file)

registry.register("write_file", "core", {
    "name": "write_file",
    "description": "Write content to a file.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to file"},
            "content": {"type": "string", "description": "File content"},
        },
        "required": ["path", "content"],
    },
}, _tool_write_file, _check_file)

registry.register("search_files", "core", {
    "name": "search_files",
    "description": "Search for files matching a glob pattern.",
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern (e.g. **/*.txt)"},
            "path": {"type": "string", "description": "Directory to search"},
            "max_results": {"type": "integer"},
        },
        "required": ["pattern"],
    },
}, _tool_search_files, _check_file)

registry.register("web_search", "core", {
    "name": "web_search",
    "description": "Search the web for information.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
}, _tool_web_search)


# ── Memory Store ───────────────────────────────────────────────────────────

class MemoryStore:
    def __init__(self, path: str = ""):
        self.path = Path(path or str(AGENT_HOME / "memory.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"targets": {}, "findings": [], "learnings": [], "skills_used": []}

    def _save(self):
        AGENT_HOME.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2))

    def add_target(self, host: str, data: dict):
        self._data["targets"][host] = {
            **self._data["targets"].get(host, {}),
            **data,
            "last_updated": datetime.now().isoformat(),
        }
        self._save()

    def add_finding(self, finding: dict):
        finding["timestamp"] = datetime.now().isoformat()
        self._data["findings"].append(finding)
        self._save()

    def add_learning(self, learning: str):
        entry = {"text": learning, "timestamp": datetime.now().isoformat()}
        self._data["learnings"].append(entry)
        self._save()

    def get_context(self) -> str:
        parts = []
        if self._data["findings"]:
            recent = self._data["findings"][-5:]
            lines = [f"- [{f.get('type','finding')}] {f.get('target','?')}: {f.get('summary','')[:200]}"
                     for f in recent]
            parts.append("Recent findings:\n" + "\n".join(lines))
        if self._data["learnings"]:
            recent_l = self._data["learnings"][-3:]
            lines = [f"- {l['text'][:200]}" for l in recent_l]
            parts.append("Learned techniques:\n" + "\n".join(lines))
        if self._data["targets"]:
            names = list(self._data["targets"].keys())[-5:]
            parts.append("Known targets: " + ", ".join(names))
        return "\n\n".join(parts)


# ── Skills System ──────────────────────────────────────────────────────────

SKILLS_DIR = AGENT_HOME / "skills"
MEMORY_DIR = AGENT_HOME / "memories"
ENTRY_DELIMITER = "\n\xa7\n"


def _read_memory_file(target: str) -> list:
    name = "USER.md" if target == "user" else "MEMORY.md"
    path = MEMORY_DIR / name
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if not raw.strip():
        return []
    entries = [e.strip() for e in raw.split(ENTRY_DELIMITER)]
    return [e for e in entries if e]


def _write_memory_file(target: str, entries: list):
    name = "USER.md" if target == "user" else "MEMORY.md"
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = MEMORY_DIR / name
    content = ENTRY_DELIMITER.join(entries)
    path.write_text(content, encoding="utf-8")


def _format_memory_block(target: str, entries: list) -> str:
    if not entries:
        return ""
    label = "USER PROFILE (who the user is)" if target == "user" else "MEMORY (agent notes)"
    sep = "\u2550" * 40
    content = ENTRY_DELIMITER.join(entries)
    return f"{sep}\n{label}\n{sep}\n{content}\n"


def _char_limit(target: str) -> int:
    return 2200 if target == "memory" else 1375


def _tool_skill_view(args: dict, **kw) -> str:
    name = args.get("name", "").strip()
    if not name:
        return json.dumps({"error": "name is required"})
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.exists():
        return json.dumps({"error": f"Skill '{name}' not found"})
    try:
        content = path.read_text()
        return json.dumps({"name": name, "content": content})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _tool_skill_manage(args: dict, **kw) -> str:
    action = args.get("action", "")
    name = args.get("name", "").strip()
    content = args.get("content", "")
    if action == "create":
        path = SKILLS_DIR / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return json.dumps({"success": True, "path": str(path)})
    elif action == "view":
        return _tool_skill_view(args, **kw)
    elif action == "list":
        skills = []
        if SKILLS_DIR.exists():
            for d in sorted(SKILLS_DIR.iterdir()):
                if d.is_dir() and (d / "SKILL.md").exists():
                    skills.append(d.name)
        return json.dumps({"skills": skills})
    return json.dumps({"error": f"Unknown action: {action}"})


registry.register("skill_view", "core", {
    "name": "skill_view",
    "description": "Load a skill by name to get its instructions.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name"},
        },
        "required": ["name"],
    },
}, _tool_skill_view)

registry.register("skill_manage", "core", {
    "name": "skill_manage",
    "description": "Create, view, or list skills.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "create | view | list"},
            "name": {"type": "string", "description": "Skill name"},
            "content": {"type": "string", "description": "Skill markdown content"},
        },
        "required": ["action"],
    },
}, _tool_skill_manage)


# ── Memory Tool ────────────────────────────────────────────────────────────

_memory_instance: Optional[MemoryStore] = None


def _ensure_memory() -> MemoryStore:
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = MemoryStore()
    return _memory_instance


def _memory_file_action(action: str, target: str, content: str = "",
                        old_text: str = "", operations: list = None) -> dict:
    if target not in ("memory", "user"):
        return {"success": False, "error": f"Invalid target '{target}'. Use 'memory' or 'user'."}
    if operations:
        entries = _read_memory_file(target)
        for op in (operations or []):
            op = op or {}
            act = op.get("action", "")
            txt = (op.get("content") or "").strip()
            old = (op.get("old_text") or "").strip()
            if act == "add" and txt:
                if txt not in entries:
                    entries.append(txt)
            elif act == "replace" and old and txt:
                for i, e in enumerate(entries):
                    if old in e:
                        entries[i] = txt
                        break
            elif act == "remove" and old:
                entries = [e for e in entries if old not in e]
        limit = _char_limit(target)
        final_size = len(ENTRY_DELIMITER.join(entries)) if entries else 0
        if final_size > limit:
            return {"success": False, "error": f"Batch result ({final_size}/{limit} chars) exceeds limit.",
                    "current_entries": entries}
        _write_memory_file(target, entries)
        return {"success": True, "message": f"Applied {len(operations)} operation(s) to {target}.",
                "entry_count": len(entries)}
    if action == "add":
        content = content.strip()
        if not content:
            return {"success": False, "error": "Content cannot be empty."}
        entries = _read_memory_file(target)
        if content in entries:
            return {"success": True, "message": "Entry already exists.", "entry_count": len(entries)}
        limit = _char_limit(target)
        current = len(ENTRY_DELIMITER.join(entries)) if entries else 0
        new_total = current + len(content) + (len(ENTRY_DELIMITER) if entries else 0)
        if new_total > limit:
            return {"success": False, "error": f"Memory at {current}/{limit} chars.",
                    "current_entries": entries}
        entries.append(content)
        _write_memory_file(target, entries)
        return {"success": True, "message": f"Entry added to {target}.",
                "entry_count": len(entries)}
    elif action == "replace":
        old_text = old_text.strip()
        content = content.strip()
        if not old_text:
            return {"success": False, "error": "old_text is required for replace."}
        if not content:
            return {"success": False, "error": "content is required for replace."}
        entries = _read_memory_file(target)
        matches = [(i, e) for i, e in enumerate(entries) if old_text in e]
        if not matches:
            return {"success": False, "error": f"No entry matched '{old_text}'.",
                    "current_entries": entries}
        if len({e for _, e in matches}) > 1:
            return {"success": False, "error": "Multiple distinct entries matched. Be more specific."}
        idx = matches[0][0]
        entries[idx] = content
        _write_memory_file(target, entries)
        return {"success": True, "message": f"Entry replaced in {target}.",
                "entry_count": len(entries)}
    elif action == "remove":
        old_text = old_text.strip()
        if not old_text:
            return {"success": False, "error": "old_text is required for remove."}
        entries = _read_memory_file(target)
        matches = [(i, e) for i, e in enumerate(entries) if old_text in e]
        if not matches:
            return {"success": False, "error": f"No entry matched '{old_text}'.",
                    "current_entries": entries}
        if len({e for _, e in matches}) > 1:
            return {"success": False, "error": "Multiple distinct entries matched. Be more specific."}
        idx = matches[0][0]
        entries.pop(idx)
        _write_memory_file(target, entries)
        return {"success": True, "message": f"Entry removed from {target}.",
                "entry_count": len(entries)}
    elif action in ("list", "get"):
        entries = _read_memory_file(target)
        return {"success": True, "entries": entries, "count": len(entries),
                "target": target}
    return {"success": False, "error": f"Unknown action '{action}'."}


def _tool_memory(args: dict, **kw) -> str:
    mem = _ensure_memory()
    action = args.get("action", "get")
    target = args.get("target", "memory")
    content = args.get("content", "")
    old_text = args.get("old_text", "")
    operations = args.get("operations")
    if target == "memory" or target == "user":
        return json.dumps(_memory_file_action(action, target, content, old_text, operations))
    if action == "get":
        ctx = mem.get_context()
        return json.dumps({"content": ctx})
    elif action == "add":
        if target == "finding":
            mem.add_finding({"type": args.get("type", "vuln"),
                             "target": args.get("target_name", ""),
                             "summary": content})
        elif target == "learning":
            mem.add_learning(content)
        return json.dumps({"success": True})
    return json.dumps({"error": f"Unknown action: {action}"})


registry.register("memory", "core", {
    "name": "memory",
    "description": "Save facts to persistent memory. Target 'memory'/'user' for MEMORY.md/USER.md.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "remove", "list", "get"],
            },
            "target": {
                "type": "string",
                "enum": ["memory", "user", "finding", "learning"],
            },
            "content": {"type": "string"},
            "old_text": {"type": "string"},
            "operations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["add", "replace", "remove"]},
                        "content": {"type": "string"},
                        "old_text": {"type": "string"},
                    },
                },
            },
        },
    },
}, _tool_memory)


# ── System Prompt Builder ──────────────────────────────────────────────────

DEFAULT_IDENTITY = """\
You are BBAgent, an autonomous bug bounty hunting AI agent.

## Workflow
You operate iteratively through these phases, **always using tools** to do the work:

### Phase 1: Reconnaissance
Use `terminal` and `web_search` to gather:
- DNS records (dig, whois, nslookup)
- Subdomains (subfinder, amass, crt.sh)
- Open ports (nmap -sV -sC)
- Web directories (gobuster, ffuf, dirb)
- Google dorking / Shodan queries
- Technology stack (whatweb, wappalyzer)
- JavaScript endpoints (linkfinder, curl)
Save recon data as files using `write_file`.

### Phase 2: Hypothesis
Analyze the recon data and write 1-3 specific, testable hypotheses.

### Phase 3: Test
For each hypothesis, run the appropriate test:
- Run the exploit/payload via `terminal`
- Use `write_file` to create test scripts
- Load relevant skills with `skill_view(name)`
- If a test FAILS, analyze WHY and revise your hypothesis (back to Phase 2)
- If a test SUCCEEDS, save the finding with `memory`

### Phase 4: Report
After verifying findings, write a report file.

## Rules
- **Always work on systems you have EXPLICIT PERMISSION to test.**
- Tool calls FIRST, explanations SECOND.
- Use `skill_view(name)` to load attack methodology skills.
- Use `skill_manage(action="create")` to save effective techniques as skills.
- Use `memory` to persist findings across sessions.
"""


def load_soul_md() -> str:
    for name in ("SOUL.md", "soul.md"):
        path = AGENT_HOME / name
        if path.exists():
            try:
                return path.read_text().strip()
            except OSError:
                pass
    return ""


def build_system_prompt(memory_context: str = "", skills_list: str = "",
                       mem_block: str = "", user_block: str = "") -> str:
    parts = []
    soul = load_soul_md()
    if soul:
        parts.append(soul)
    parts.append(DEFAULT_IDENTITY.format(SKILLS_DIR=str(SKILLS_DIR)))
    if skills_list:
        parts.append(f"## Loadable Skills\n\nAvailable skills:\n{skills_list}")
    if memory_context:
        parts.append(f"## Bounty Memory\n\n{memory_context}")
    if mem_block:
        parts.append(mem_block)
    if user_block:
        parts.append(user_block)
    return "\n\n".join(parts)


# ── LLM Client ─────────────────────────────────────────────────────────────

def create_llm_client(config: dict):
    from openai import OpenAI
    kwargs = {"api_key": config.get("api_key")}
    base_url = config.get("base_url", "")
    if base_url:
        kwargs["base_url"] = base_url
    if not kwargs["api_key"]:
        kwargs["api_key"] = "no-key-required"
    return OpenAI(**kwargs)


# ── Agent Loop ─────────────────────────────────────────────────────────────

def build_skills_list() -> str:
    if not SKILLS_DIR.exists():
        return ""
    lines = []
    for d in sorted(SKILLS_DIR.iterdir()):
        skill_file = d / "SKILL.md"
        if skill_file.exists():
            content = skill_file.read_text()
            desc = ""
            m = re.search(r'^description:\s+(.+)$', content, re.MULTILINE)
            if m:
                desc = m.group(1).strip()
            lines.append(f"  - {d.name}: {desc}")
    return "\n".join(lines) if lines else ""


# ── MCP Client ────────────────────────────────────────────────────────────

class MCPClient:
    def __init__(self, name: str, command: str, args: list = None,
                 env: dict = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.process = None
        self.tools = []
        self._id = 0

    def connect(self, timeout: int = 30) -> bool:
        try:
            merged_env = os.environ.copy()
            merged_env.update(self.env)
            resolved_cmd = shutil.which(self.command)
            if not resolved_cmd:
                raise FileNotFoundError(f"Command '{self.command}' not found in PATH")
            self.process = subprocess.Popen(
                [resolved_cmd] + self.args,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=merged_env, text=True,
            )
            resp = self._rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "bbagent", "version": "1.0.0"},
            }, timeout)
            if resp is None:
                return False
            self._notify("notifications/initialized", {})
            tools_resp = self._rpc("tools/list", {}, timeout)
            if tools_resp and "tools" in tools_resp:
                self.tools = tools_resp["tools"]
            return True
        except Exception as e:
            _safe_print(f"  MCP '{self.name}': {e}")
            self.disconnect()
            return False

    def _read_line_with_timeout(self, timeout: int) -> str:
        try:
            readable, _, _ = select.select([self.process.stdout], [], [], timeout)
            if not readable:
                raise TimeoutError(f"MCP '{self.name}' read timed out after {timeout}s")
        except (TypeError, ValueError, OSError):
            result_q = queue.Queue()
            read_thread = threading.Thread(
                target=lambda: result_q.put(self.process.stdout.readline()),
                daemon=True,
            )
            read_thread.start()
            read_thread.join(timeout)
            if read_thread.is_alive():
                raise TimeoutError(f"MCP '{self.name}' read timed out after {timeout}s")
            line = result_q.get_nowait()
            if not line:
                raise ConnectionError(f"MCP '{self.name}' closed stdout")
            return line
        line = self.process.stdout.readline()
        if not line:
            raise ConnectionError(f"MCP '{self.name}' closed stdout")
        return line

    def _rpc(self, method: str, params: dict, timeout: int = 30) -> dict:
        self._id += 1
        req = json.dumps({"jsonrpc": "2.0", "id": self._id,
                          "method": method, "params": params})
        self.process.stdin.write(req + "\n")
        self.process.stdin.flush()
        line = self._read_line_with_timeout(timeout)
        resp = json.loads(line)
        if "error" in resp:
            raise Exception(str(resp["error"]))
        return resp.get("result", {})

    def _notify(self, method: str, params: dict):
        req = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        self.process.stdin.write(req + "\n")
        self.process.stdin.flush()

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        try:
            result = self._rpc("tools/call", {"name": tool_name, "arguments": arguments})
            if result is None:
                return json.dumps({"error": f"MCP server '{self.name}' not responding"})
            content = result.get("content", [])
            text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
            text = "\n".join(text_parts)
            return json.dumps({"error": text}) if result.get("isError") else json.dumps({"success": True, "output": text})
        except Exception as e:
            return json.dumps({"error": f"MCP '{self.name}.{tool_name}': {e}"})

    def get_tool_schemas(self) -> list:
        return [{
            "name": t.get("name", "unknown"),
            "description": t.get("description", ""),
            "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
        } for t in self.tools]

    def disconnect(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None


# ── Session Search (SQLite FTS5) ─────────────────────────────────────────

class SessionSearch:
    """SQLite-backed session storage with FTS5 full-text search.

    Indexes session messages so the agent can search past conversations.
    Uses sqlite3 (stdlib) with FTS5 for fast text search.
    """

    def __init__(self, db_path: str = "", prune_days: int = 90):
        self.db_path = Path(db_path or str(AGENT_HOME / "state.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fts_ok = False
        self._conn = None
        self._init_sessions = False
        self._prune_days = prune_days
        self._prune_counter = 0
        self._init()

    def _init(self):
        try:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._fts_ok = self._probe_fts5()  # probe first so _init_schema can create FTS5 tables
            self._init_schema()
            atexit.register(self.close)
        except Exception as e:
            _safe_print(f"  [!] Session search init failed: {e}")
            self._conn = None
            self._fts_ok = False

    def _is_fts_unavailable(self, exc: sqlite3.OperationalError) -> bool:
        return "no such module" in str(exc).lower() and "fts5" in str(exc).lower()

    def _probe_fts5(self) -> bool:
        if not self._conn:
            return False
        try:
            self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _hermes_fts_probe USING fts5(x)")
            self._conn.execute("DROP TABLE IF EXISTS _hermes_fts_probe")
            return True
        except sqlite3.OperationalError as exc:
            if self._is_fts_unavailable(exc):
                _safe_print("  [!] SQLite FTS5 not available - session search uses LIKE fallback")
                return False
            raise

    def _init_schema(self):
        if not self._conn:
            return
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                model TEXT,
                started_at REAL NOT NULL,
                ended_at REAL,
                message_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                tool_name TEXT,
                tool_calls TEXT,
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, timestamp);
        """)
        self._conn.commit()
        if self._fts_ok:
            try:
                self._conn.executescript("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                        content, tool_name, tool_calls
                    );
                    CREATE TRIGGER IF NOT EXISTS messages_fts_insert
                        AFTER INSERT ON messages BEGIN
                        INSERT INTO messages_fts(rowid, content, tool_name, tool_calls)
                        VALUES (new.id, new.content, new.tool_name, new.tool_calls);
                    END;
                    CREATE TRIGGER IF NOT EXISTS messages_fts_delete
                        AFTER DELETE ON messages BEGIN
                        DELETE FROM messages_fts WHERE rowid = old.id;
                    END;
                    CREATE TRIGGER IF NOT EXISTS messages_fts_update
                        AFTER UPDATE ON messages BEGIN
                        DELETE FROM messages_fts WHERE rowid = old.id;
                        INSERT INTO messages_fts(rowid, content, tool_name, tool_calls)
                        VALUES (new.id, new.content, new.tool_name, new.tool_calls);
                    END;
                """)
                self._conn.commit()
            except sqlite3.OperationalError as exc:
                if self._is_fts_unavailable(exc):
                    self._fts_ok = False
                    return
                raise

    def index_session(self, session_id: str, model: str, messages: list):
        """Index a session and its messages into the DB."""
        if not self._conn:
            return
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            now = time.time()
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions (id, model, started_at, ended_at, message_count) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, model, now, now, len(messages)),
            )
            # Delete old messages for this session, then re-insert
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            for msg in messages:
                role = msg.get("role", "")
                content = str(msg.get("content", ""))
                tc = msg.get("tool_calls")
                tool_calls_str = json.dumps(tc) if tc else ""
                tool_name = ""
                if tc and isinstance(tc, list) and len(tc) > 0:
                    fn = tc[0].get("function", {})
                    tool_name = fn.get("name", "")
                self._conn.execute(
                    "INSERT INTO messages (session_id, role, content, tool_name, tool_calls, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, role, content, tool_name, tool_calls_str, now),
                )
            self._conn.commit()
            # Periodic pruning: every 10 index calls
            self._prune_counter += 1
            if self._prune_counter % 10 == 0:
                self.prune_older_than(self._prune_days)
        except Exception:
            try:
                self._conn.rollback()
            except Exception:
                pass

    def search(self, query: str, max_results: int = 10) -> list:
        """Search past sessions. Returns list of dicts with session_id, model, content snippet."""
        if not self._conn:
            return []
        try:
            if self._fts_ok:
                # Sanitize FTS query - escape special chars, wrap words
                safe = re.sub(r'[^\w\s\-]', ' ', query).strip()
                terms = [t for t in safe.split() if t]
                if not terms:
                    return []
                # Use phrase prefix matching for each term
                fts_query = " AND ".join(f'"{t}"*' for t in terms)
                rows = self._conn.execute(
                    """
                    SELECT DISTINCT s.id AS session_id, s.model, m.content, m.role,
                           rank AS relevance
                    FROM messages_fts
                    JOIN messages m ON messages_fts.rowid = m.id
                    JOIN sessions s ON m.session_id = s.id
                    WHERE messages_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, max_results),
                ).fetchall()
            else:
                # Fallback: LIKE search (works without FTS5)
                like = f"%{query}%"
                rows = self._conn.execute(
                    """
                    SELECT DISTINCT s.id AS session_id, s.model, m.content, m.role,
                           0.0 AS relevance
                    FROM messages m
                    JOIN sessions s ON m.session_id = s.id
                    WHERE m.content LIKE ?
                    ORDER BY s.started_at DESC
                    LIMIT ?
                    """,
                    (like, max_results),
                ).fetchall()
            results = []
            seen = set()
            for r in rows:
                sid = r["session_id"]
                if sid in seen:
                    continue
                seen.add(sid)
                results.append({
                    "session_id": sid,
                    "model": r["model"] or "",
                    "snippet": (r["content"] or "")[:500],
                    "role": r["role"],
                })
            return results
        except Exception as e:
            return [{"error": str(e)}]

    def _index_existing_sessions(self):
        """One-time scan of on-disk session JSON files to populate the FTS index."""
        if self._init_sessions or not self._conn:
            return
        self._init_sessions = True
        sessions_dir = AGENT_HOME / "sessions"
        if not sessions_dir.is_dir():
            return
        for fpath in sorted(sessions_dir.glob("*.json")):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                sid = data.get("session_id", "")
                model = data.get("model", "")
                msgs = data.get("messages", [])
                if sid:
                    self.index_session(sid, model, msgs)
            except (json.JSONDecodeError, OSError):
                pass
        # Prune old sessions after indexing existing ones
        self.prune_older_than(self._prune_days)

    def prune_older_than(self, days: int):
        """Delete sessions older than `days` from both SQLite and JSON files."""
        if not self._conn:
            return
        cutoff = time.time() - days * 86400
        try:
            # Find old session IDs
            old_ids = [
                r["id"] for r in self._conn.execute(
                    "SELECT id FROM sessions WHERE started_at < ?", (cutoff,)
                ).fetchall()
            ]
            if not old_ids:
                return
            placeholders = ",".join("?" for _ in old_ids)
            # Delete messages (FTS triggers will clean messages_fts)
            self._conn.execute(
                f"DELETE FROM messages WHERE session_id IN ({placeholders})", old_ids
            )
            # Delete sessions
            self._conn.execute(
                f"DELETE FROM sessions WHERE id IN ({placeholders})", old_ids
            )
            self._conn.commit()
            # Clean up JSON files on disk
            sessions_dir = AGENT_HOME / "sessions"
            if sessions_dir.is_dir():
                old_ids_set = set(old_ids)
                for fpath in sessions_dir.glob("*.json"):
                    try:
                        sid = json.loads(fpath.read_text()).get("session_id", "")
                        if sid in old_ids_set:
                            fpath.unlink(missing_ok=True)
                    except (json.JSONDecodeError, OSError):
                        pass
        except Exception:
            try:
                self._conn.rollback()
            except Exception:
                pass

    def stats(self) -> dict:
        """Return session stats: count, oldest/newest timestamps, DB file size."""
        result = {
            "session_count": 0,
            "oldest_at": None,
            "newest_at": None,
            "db_size_bytes": 0,
        }
        if not self._conn:
            return result
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) AS cnt, MIN(started_at) AS oldest, MAX(started_at) AS newest "
                "FROM sessions"
            ).fetchone()
            result["session_count"] = row["cnt"] or 0
            if row["oldest"]:
                result["oldest_at"] = datetime.fromtimestamp(row["oldest"]).isoformat()
            if row["newest"]:
                result["newest_at"] = datetime.fromtimestamp(row["newest"]).isoformat()
        except Exception:
            pass
        try:
            result["db_size_bytes"] = self.db_path.stat().st_size
        except OSError:
            pass
        return result

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


_session_search_instance: Optional[SessionSearch] = None


def _load_session_search_config() -> dict:
    """Read session_search config from config.yaml (lightweight, no provider detection)."""
    config_path = AGENT_HOME / "config.yaml"
    if config_path.exists():
        try:
            cfg = yaml.safe_load(config_path.read_text()) or {}
            return cfg.get("session_search", {}) or {}
        except Exception:
            pass
    return {}


def _ensure_session_search() -> SessionSearch:
    global _session_search_instance
    if _session_search_instance is None:
        ss_cfg = _load_session_search_config()
        prune_days = int(ss_cfg.get("prune_days", 90))
        _session_search_instance = SessionSearch(prune_days=prune_days)
        _session_search_instance._index_existing_sessions()
    return _session_search_instance


def _tool_session_search(args: dict, **kw) -> str:
    query = args.get("query", "")
    if not query:
        return json.dumps({"error": "query is required"})
    max_results = args.get("max_results", 10)
    ss = _ensure_session_search()
    results = ss.search(query, max_results)
    if not results:
        return json.dumps({"results": [], "message": "No matching sessions found."})
    return json.dumps({"results": results, "count": len(results)})


def _check_session_search() -> bool:
    return True  # available as long as sqlite3 works


registry.register("session_search", "core", {
    "name": "session_search",
    "description": "Search past conversation sessions using full-text search. Use to find previous findings, commands, or discussions.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results (default 10)"},
        },
        "required": ["query"],
    },
}, _tool_session_search, _check_session_search)


class BBAgent:
    def __init__(self, config: dict):
        self.config = config
        self.client = create_llm_client(config)
        self.model = config.get("model", "gpt-4o")
        self.max_iterations = config.get("max_iterations", 30)
        self.max_tokens = config.get("max_tokens", 8192)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self.messages: List[dict] = []
        self.cached_system_prompt: Optional[str] = None
        self.mem = _ensure_memory()
        self._memory_snapshot = {"memory": [], "user": []}
        sr_cfg = config.get("self_review", {}) or {}
        self._enable_self_review = bool(sr_cfg.get("enabled", True))
        self._review_interval = int(sr_cfg.get("interval", 3))
        self._review_max_tokens = int(sr_cfg.get("max_tokens", 1000))
        self._review_turn_counter = 0
        tool_cfg = config.get("tools", {})
        self.enabled_tools: Set[str] = set()
        toolset_map: Dict[str, List[str]] = {}
        for tname in registry.get_tool_names():
            ts = registry.get_toolset_for(tname) or "core"
            toolset_map.setdefault(ts, []).append(tname)
        for ts, tools in toolset_map.items():
            if tool_cfg.get(ts, True):
                self.enabled_tools.update(tools)
        mcp_cfg = config.get("mcp_servers", {}) or {}
        self._mcp_clients: Dict[str, MCPClient] = {}
        for name, srv in mcp_cfg.items():
            if not isinstance(srv, dict):
                continue
            cmd = srv.get("command", "")
            if not cmd:
                continue
            client = MCPClient(name, cmd, srv.get("args", []), srv.get("env", {}))
            if client.connect():
                self._mcp_clients[name] = client
                for schema in client.get_tool_schemas():
                    def _mk(tn, cl):
                        return lambda a, **kw: cl.call_tool(tn, a)
                    registry.register(schema["name"], f"mcp-{name}", schema, _mk(schema["name"], client))
                    self.enabled_tools.add(schema["name"])
        self.tool_schemas = registry.get_schemas(self.enabled_tools)
        atexit.register(self._shutdown_mcp)

    def _shutdown_mcp(self):
        for c in getattr(self, '_mcp_clients', {}).values():
            try:
                c.disconnect()
            except Exception:
                pass

    def _rebuild_system_prompt(self):
        mem_ctx = self.mem.get_context()
        skills_list = build_skills_list()
        mem_entries = _read_memory_file("memory")
        user_entries = _read_memory_file("user")
        self._memory_snapshot = {"memory": mem_entries, "user": user_entries}
        self.cached_system_prompt = build_system_prompt(
            mem_ctx, skills_list,
            _format_memory_block("memory", mem_entries),
            _format_memory_block("user", user_entries))

    def run(self, user_message: str) -> str:
        if self.cached_system_prompt is None:
            self._rebuild_system_prompt()
        self.messages.append({"role": "user", "content": user_message})
        self._maybe_compress_context()
        for iteration in range(self.max_iterations):
            api_messages = [{"role": "system", "content": self.cached_system_prompt}, *self.messages]
            try:
                response = self.client.chat.completions.create(
                    model=self.model, messages=api_messages,
                    tools=self.tool_schemas or None, max_tokens=self.max_tokens)
            except Exception:
                time.sleep(2)
                try:
                    response = self.client.chat.completions.create(
                        model=self.model, messages=api_messages,
                        tools=self.tool_schemas or None, max_tokens=self.max_tokens)
                except Exception as e2:
                    self._save_session()
                    return f"API error after retry: {e2}"
            choice = response.choices[0]
            msg = choice.message
            if msg.tool_calls:
                self.messages.append({"role": "assistant", "content": msg.content or "",
                    "tool_calls": [{"id": tc.id, "type": "function",
                                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                   for tc in msg.tool_calls]})
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        self.messages.append({"role": "tool", "tool_call_id": tc.id,
                            "content": json.dumps({"error": f"Invalid JSON: {tc.function.arguments[:200]}"})})
                        continue
                    result = registry.dispatch(tc.function.name, args, task_id=self.session_id, _agent_config=self.config)
                    self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            else:
                final = msg.content or ""
                self.messages.append({"role": "assistant", "content": final})
                self._save_session()
                self._background_review("", final)
                return final
        self._save_session()
        return "Max iterations reached."

    def _maybe_compress_context(self):
        limit = self.config.get("context_limit", 128000)
        total = sum(len(json.dumps(m, ensure_ascii=False)) for m in self.messages)
        if total < limit * 0.5 or len(self.messages) <= 12:
            return
        self.messages = [{"role": "user", "content": "[Earlier context compressed]"},
                         *self.messages[-10:]]

    def _save_session(self):
        # JSON file (backward compat)
        path = AGENT_HOME / "sessions" / f"{self.session_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(json.dumps({"session_id": self.session_id, "model": self.model,
                                        "timestamp": datetime.now().isoformat(), "messages": self.messages}))
        except OSError:
            pass
        # FTS5 index (searchable)
        try:
            ss = _ensure_session_search()
            ss.index_session(self.session_id, self.model, self.messages)
        except Exception:
            pass

    def _background_review(self, user_msg: str, assistant_response: str):
        if not self._enable_self_review or len(assistant_response) < 20:
            return
        if self._review_interval > 0:
            self._review_turn_counter += 1
            if self._review_turn_counter % self._review_interval != 0:
                return
        try:
            api_messages = [{"role": "system", "content": self.cached_system_prompt},
                            *self.messages[-4:],
                            {"role": "user", "content": "Review and return JSON: {memory_entries, user_entries, skill_to_create, skill_content}"}]
            resp = self.client.chat.completions.create(model=self.model, messages=api_messages, max_tokens=self._review_max_tokens, temperature=0.1)
            raw = resp.choices[0].message.content or ""
            raw = raw.strip().lstrip("```").rsplit("```", 1)[0].strip()
            data = json.loads(raw)
            if not isinstance(data, dict):
                return
            for e in data.get("memory_entries", []):
                if isinstance(e, str) and e.strip():
                    _memory_file_action("add", "memory", e.strip())
            for e in data.get("user_entries", []):
                if isinstance(e, str) and e.strip():
                    _memory_file_action("add", "user", e.strip())
            sn, sc = data.get("skill_to_create"), data.get("skill_content")
            if sn and sc and isinstance(sn, str) and isinstance(sc, str):
                (SKILLS_DIR / sn / "SKILL.md").parent.mkdir(parents=True, exist_ok=True)
                (SKILLS_DIR / sn / "SKILL.md").write_text(sc)
        except Exception:
            pass

    def chat(self, message: str) -> str:
        return self.run(message)

    def interactive(self):
        _safe_print(f"\n{'='*50}")
        _safe_print("  BBAgent - Bug Bounty AI Agent")
        _safe_print(f"  Session: {self.session_id}")
        _safe_print(f"  Model: {self.model}")
        _safe_print(f"  Tools: {len(self.tool_schemas)} loaded")
        _safe_print("  Commands: /search <query>, /stats, /prune, /help, /clear, /exit")
        _safe_print(f"{'='*50}\n")
        while True:
            try:
                user_input = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input or user_input.lower() in ("exit", "quit", "/exit", "/quit"):
                break
            if user_input == "/search" or user_input.startswith("/search "):
                query = user_input[len("/search "):].strip() if len(user_input) > len("/search ") else ""
                self._cmd_search(query)
                continue
            if user_input == "/stats":
                self._cmd_stats()
                continue
            if user_input == "/prune":
                self._cmd_prune()
                continue
            if user_input == "/help":
                self._cmd_help()
                continue
            if user_input == "/clear":
                self._cmd_clear()
                continue
            print()
            _safe_print(f"\n  {self.run(user_input)}\n")

    @staticmethod
    def _cmd_stats():
        """Handle /stats — show session database stats."""
        ss = _ensure_session_search()
        st = ss.stats()
        _safe_print(f"\n  {'='*50}")
        _safe_print("  Session Database Stats")
        _safe_print(f"  {'='*50}")
        _safe_print(f"  Sessions indexed: {st['session_count']}")
        if st["oldest_at"]:
            _safe_print(f"  Oldest session:   {st['oldest_at']}")
        if st["newest_at"]:
            _safe_print(f"  Newest session:   {st['newest_at']}")
        _safe_print(f"  DB file size:     {st['db_size_bytes']:,} bytes")
        _safe_print(f"  {'='*50}\n")

    @staticmethod
    def _cmd_prune():
        """Handle /prune — force prune old sessions."""
        ss = _ensure_session_search()
        ss_cfg = _load_session_search_config()
        days = int(ss_cfg.get("prune_days", 90))

        _safe_print(f"\n  {'='*50}")
        _safe_print("  Pruning Sessions")
        _safe_print(f"  {'='*50}")
        _safe_print(f"  Retention: {days} days")

        before = ss.stats()
        _safe_print(f"  Sessions before: {before['session_count']}")

        ss.prune_older_than(days)

        after = ss.stats()
        _safe_print(f"  Sessions after:  {after['session_count']}")
        removed = before['session_count'] - after['session_count']
        _safe_print(f"  Removed:         {removed}")
        _safe_print(f"  {'='*50}\n")

    @staticmethod
    def _cmd_help():
        """Handle /help — show available commands."""
        _safe_print(f"\n  {'='*50}")
        _safe_print("  Available Commands")
        _safe_print(f"  {'='*50}")
        _safe_print("")
        _safe_print("  /search <query>   Search past sessions for matching text")
        _safe_print("  /stats            Show session database statistics")
        _safe_print("  /prune            Force-prune old sessions (configurable retention)")
        _safe_print("  /help             Show this help message")
        _safe_print("  /clear            Clear the terminal screen")
        _safe_print("  /exit, /quit      Exit the interactive session")
        _safe_print("  exit, quit        Exit the interactive session")
        _safe_print(f"")
        _safe_print(f"  For one-shot mode: python bbagent.py \"<prompt>\"")
        _safe_print(f"  {'='*50}\n")

    @staticmethod
    def _cmd_clear():
        """Handle /clear — clear the terminal screen."""
        os.system("cls" if os.name == "nt" else "clear")

    @staticmethod
    def _cmd_search(query: str):
        """Handle /search <query> — search past sessions."""
        if not query:
            _safe_print("  Usage: /search <query>")
            return
        ss = _ensure_session_search()
        results = ss.search(query)
        if not results:
            _safe_print("  No matching sessions found.")
            return
        _safe_print(f"\n  {'='*50}")
        _safe_print(f"  Found {len(results)} session(s) for: {query}")
        _safe_print(f"  {'='*50}")
        for r in results:
            if "error" in r:
                _safe_print(f"  [!] {r['error']}")
                continue
            _safe_print(f"\n  [Session: {r.get('session_id', '?')}]")
            _safe_print(f"  Model: {r.get('model', '?')}")
            _safe_print(f"  Snippet: {r.get('snippet', '')[:300]}")
        _safe_print(f"  {'='*50}\n")


# ── Subagent ──────────────────────────────────────────────────────────────
#
# The subagent runs a full tool-calling loop (same as the parent agent) so it
# can use terminal, file, web_search, and any MCP tools the parent has.

def _spawn_subagent(config: dict, goal: str, context: str = "",
                    timeout: int = 120,
                    tool_schemas: list = None,
                    session_id: str = "") -> str:
    sub_config = dict(config)
    sub_config["max_iterations"] = config.get("subagent_max_iterations", 15)
    sub_tool_schemas = tool_schemas or []
    result = {"result": None, "error": None}

    def _run():
        try:
            from openai import OpenAI
            client = OpenAI(api_key=sub_config["api_key"],
                            base_url=sub_config.get("base_url", ""))
            msgs = []
            if context:
                msgs.append({"role": "user", "content": context})
            msgs.append({"role": "user", "content": goal})

            max_it = int(sub_config.get("max_iterations", 15))
            for _ in range(max_it):
                resp = client.chat.completions.create(
                    model=sub_config.get("model", "gpt-4o"),
                    messages=msgs,
                    tools=sub_tool_schemas or None,
                    max_tokens=sub_config.get("max_tokens", 4096),
                )
                choice = resp.choices[0]
                msg = choice.message

                if msg.tool_calls:
                    tc_list = [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name,
                                             "arguments": tc.function.arguments}}
                               for tc in msg.tool_calls]
                    msgs.append({"role": "assistant", "content": msg.content or "",
                                 "tool_calls": tc_list})
                    for tc in msg.tool_calls:
                        try:
                            t_args = json.loads(tc.function.arguments)
                        except (json.JSONDecodeError, TypeError):
                            t_args = {}
                        t_result = registry.dispatch(
                            tc.function.name, t_args,
                            task_id=session_id, _agent_config=sub_config,
                        )
                        msgs.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": t_result})
                else:
                    result["result"] = msg.content or ""
                    return
            result["result"] = "[subagent max iterations reached]"
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        return json.dumps({"error": f"Subagent timed out after {timeout}s"})
    if result["error"]:
        return json.dumps({"error": result["error"]})
    return json.dumps({"result": result["result"]})


def _tool_delegate_task(args: dict, **kw) -> str:
    goal = args.get("goal", "")
    if not goal:
        return json.dumps({"error": "goal is required"})
    agent_config = kw.get("_agent_config", {})
    session_id = kw.get("task_id", "")
    # Build tool schemas from the parent's enabled tools (excluding delegate_task)
    tools = set(registry.get_tool_names())
    tools.discard("delegate_task")
    sub_schemas = registry.get_schemas(tools)
    return _spawn_subagent(
        agent_config, goal, args.get("context", ""),
        args.get("timeout", 120),
        tool_schemas=sub_schemas,
        session_id=session_id,
    )


registry.register("delegate_task", "core", {
    "name": "delegate_task",
    "description": "Spawn a subagent to complete a focused task. The subagent has access to the same tools as the parent (terminal, read_file, write_file, etc).",
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "context": {"type": "string"},
            "timeout": {"type": "integer"},
        },
        "required": ["goal"],
    },
}, _tool_delegate_task)


# ── Uninstall ──────────────────────────────────────────────────────────────

def _do_uninstall():
    print("\nUninstalling BBAgent...")
    bbagent_dir = Path.home() / ".bbagent"
    if bbagent_dir.exists():
        shutil.rmtree(bbagent_dir)
        print(f"  Removed: {bbagent_dir}")
    else:
        print(f"  Not found: {bbagent_dir}")
    script_dir = Path(__file__).parent
    for fname in ("bbagent.py", "setup_bbagent.py", "BBAGENT_BLUEPRINT.md"):
        path = script_dir / fname
        if path.exists():
            path.unlink()
            print(f"  Removed: {path}")
    print("\nBBAgent uninstalled.\n")


# ── CLI Entry Point ────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="BBAgent - Bug Bounty AI Agent")
    parser.add_argument("prompt", nargs="?", help="Prompt to run (non-interactive)")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("--model", default="", help="Model name")
    parser.add_argument("--provider", default="", help="Provider: openai, ollama, ...")
    parser.add_argument("--base-url", default="", help="API base URL")
    parser.add_argument("--max-iterations", type=int, default=0, help="Max tool-calling iterations")
    parser.add_argument("--no-self-review", action="store_true", help="Disable self-review")
    parser.add_argument("--self-review-interval", type=int, default=None, help="Review interval")
    parser.add_argument("--retention", type=int, default=0,
                        help="Session retention in days (saved to config.yaml)")
    parser.add_argument("--prune-now", action="store_true",
                        help="Immediately prune old sessions using current retention setting")
    parser.add_argument("--uninstall", action="store_true", help="Remove ~/.bbagent/ and BBAgent files")
    args = parser.parse_args()
    if args.uninstall:
        _do_uninstall()
        return
    if args.retention > 0:
        cfg_path = AGENT_HOME / "config.yaml"
        cfg = {}
        if cfg_path.exists():
            try:
                cfg = yaml.safe_load(cfg_path.read_text()) or {}
            except Exception:
                pass
        cfg.setdefault("session_search", {})["prune_days"] = args.retention
        AGENT_HOME.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(yaml.dump(cfg, default_flow_style=False))
        print(f"  Session retention set to {args.retention} days in {cfg_path}")
        return
    if args.prune_now:
        ss_cfg = _load_session_search_config()
        days = int(ss_cfg.get("prune_days", 90))
        ss = _ensure_session_search()
        print(f"  Pruning sessions older than {days} days...")
        ss.prune_older_than(days)
        st = ss.stats()
        print(f"  Prune complete. {st['session_count']} sessions remaining.")
        return
    config = load_config()
    if args.model:
        config["model"] = args.model
    if args.provider:
        config["provider"] = args.provider
    if args.base_url:
        config["base_url"] = args.base_url
    if args.max_iterations > 0:
        config["max_iterations"] = args.max_iterations
    if args.no_self_review:
        config["self_review"] = config.get("self_review", {})
        config["self_review"]["enabled"] = False
    if args.self_review_interval is not None:
        config["self_review"] = config.get("self_review", {})
        config["self_review"]["interval"] = args.self_review_interval
    agent = BBAgent(config)
    if args.interactive:
        agent.interactive()
    elif args.prompt:
        result = agent.run(args.prompt)
        print(result)
    else:
        print("BBAgent started. Run with --help for options.")


if __name__ == "__main__":
    main()
