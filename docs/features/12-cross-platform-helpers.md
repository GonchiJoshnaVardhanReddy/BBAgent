# Cross-platform Helpers

## What It Does
A collection of utilities that make BBAgent work correctly across Windows, macOS, and Linux.

## Components

### 1. Emoji-Safe Printing (`_safe_print`)
Terminals on Windows (especially `cmd.exe` with `cp1252` encoding) can't display emoji. `_safe_print()` probes stdout encoding once, then falls back to ASCII replacements:

| Emoji | Fallback |
|-------|----------|
| 🔌 (plug) | `[plug]` |
| 🖥️ (pc) | `[pc]` |
| ⚠️ (warning) | `[!]` |
| 💡 (idea) | `[i]` |
| 🔧 (tool) | `[tool]` |
| 📝 (note) | `[note]` |
| ✅ (check) | `[OK]` |
| ❌ (cross) | `[X]` |
| ⭐ (star) | `[*]` |

If the encoding can't handle the character, it falls back to ASCII replace mode.

### 2. Path Expansion (`Path.expanduser()`)
All file paths use `Path(path).expanduser()` so `~` references work on all platforms.

### 3. MCP Server Path Resolution
- `shutil.which()` resolves `.cmd` files on Windows (Node.js/npx)
- `select.select()` fallback on Windows: thread-based timeout for MCP reads

### 4. Subprocess Handling
- `shell=True` for cross-platform terminal commands
- `encoding="utf-8"` and `errors="replace"` for consistent text output
- Timeout handling via `subprocess.TimeoutExpired`

### 5. Setup Script Compatibility
`setup_bbagent.py` detects platform-specific package managers:
- **Windows**: `winget`, MSI download fallback
- **Linux**: `apt` (Debian/Ubuntu), `brew` (Homebrew on Linux)
- **macOS**: `brew` (Homebrew)
