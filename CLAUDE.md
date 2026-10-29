# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in development mode (required before running CLI or tests)
pip install -e .

# Run all tests
python -m pytest tests/

# Run a single test file
python -m pytest tests/test_extract_claude_logs_aligned.py

# Run a single test by name
python -m pytest tests/test_error_handling.py::TestErrorHandling::test_init_fallback_all_dirs_fail

# Lint (matches CI config)
flake8 src/extract_claude_logs.py --max-line-length=100

# Run the interactive UI
claude-start

# Run the CLI
claude-extract --help
claude-extract --recent 5
claude-extract --all --output ~/my-logs
claude-extract --search "query" --project /path/to/repo
claude-extract --format json --all
```

## Architecture

All source lives in `src/` (no package nesting — `pyproject.toml` sets `package-dir = "" = "src"`). There are no external dependencies; everything is pure Python.

**Entry points** (`pyproject.toml` `[project.scripts]`):
- `claude-extract` / `claude-logs` / `claude-start` → `extract_claude_logs:launch_interactive`
- `claude-search` → `search_cli:main`

**Module responsibilities:**

| Module | Role |
|---|---|
| `extract_claude_logs.py` | Core extractor. `ClaudeConversationExtractor` reads JSONL, converts to markdown/JSON/HTML. `encode_project_path()` maps filesystem paths to Claude's encoded project dir names. `main()` handles CLI args. `launch_interactive()` delegates to the UI or falls back to CLI. |
| `interactive_ui.py` | `InteractiveUI` — menu-driven terminal UI for session browsing and bulk extraction. |
| `realtime_search.py` | `RealTimeSearch` — threaded, keystroke-driven search with `KeyboardHandler`, `TerminalDisplay`, and a background `search_worker`. |
| `search_conversations.py` | `ConversationSearcher` — multi-mode search (smart/exact/regex/semantic) with relevance scoring and optional disk-based caching. |
| `search_cli.py` | Thin CLI wrapper around `ConversationSearcher`. |

**Data flow:** Claude Code writes conversation turns to `~/.claude/projects/<encoded-path>/<session-id>.jsonl`. Each line is a JSON object with a `type` field (`user`, `assistant`, `tool_use`, `tool_result`, `system`). The extractor reads these and emits clean markdown with `## Human` / `## Assistant` headings. `--detailed` mode also surfaces tool calls and system messages.

**Environment variables:**
- `CLAUDE_DIR` or `PROJECT_DIR` — override the default `~/.claude/projects` source directory.

**Tests:** `tests/conftest.py` adds `src/` to `sys.path`. Fixtures live in `tests/fixtures/`. Tests cover threading (`test_realtime_search_threading.py`), UI rendering (`test_realtime_search_ui.py`), integration flows, and error handling.