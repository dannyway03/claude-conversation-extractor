# Backup Sessions Python Port Design

2026-10-30

## Overview

Port `scripts/backup-sessions.sh` and `scripts/init-session-backup.sh` to a single Python module
`src/backup_sessions.py`, registered as the `claude-backup` CLI entry point with
`init` and `run` subcommands.

## Architecture

```
src/backup_sessions.py
  cmd_init(project_dir, backup_dir)                    — interactive setup, writes backup-config.json
  cmd_run(backup_dir, fast, status)       — reads config, syncs files
  main()                                  — argparse dispatcher

pyproject.toml
  claude-backup = "backup_sessions:main"
```

### Subcommands

```
claude-backup init [project_dir, backup-dir]
claude-backup run  [backup-dir] [--fast] [--status]
```

## Config

`backup-config.json` lives in `<backup-dir>/backup-config.json` — same location and schema as the shell scripts (version
1, `claude_dir`, `projects` array). Existing configs load without migration.

```json
{
  "version": 1,
  "claude_dir": "~/.claude",
  "projects": [ "*" ]
}
```

## `cmd_init` Flow

1. Resolve `backup_dir` (default: cwd)
2. Discover `project_dir` subdirectories
3. Print numbered list with decoded paths
    - Decode rule: leading `<char>--` → `<char>:/` (Windows), `--` → `/`, `-` → `/`
    - Fixes the broken `sed` regex in the shell script
4. Prompt: number (s) / `all` / `none` (default: `all`)
5. If config exists, prompt overwrite `[y/N]`
6. Write `backup-config.json` via `json.dumps` (fixes shell string-concat injection risk)
7. Print summary and next-step hint

## `cmd_run` Flow

1. Resolve `backup_dir`, load and validate `backup-config.json`
2. Expand project patterns (`*` = glob, literal = direct)
3. For each project:
   a. Copy `*.jsonl`, `*.meta.json` (top-level only)
   b. Sync `<session-uuid>/subagents/` and `<session-uuid>/tool-results/`
    - Copy changed files (`filecmp.cmp` default, `os.stat` size+mtime if `--fast`)
    - Remove stale destination files
    - Prune empty directories c. Remove stale top-level `*.jsonl` / `*.meta.json`
4. Print summary: copied / unchanged / removed

**explain: Remove stale destination files**. define stale.

`--status` prints backed-up file counts, files up-to-date, to update, etc. and exits without syncing.  
`--fast` uses `os.stat` size+mtime instead of byte-by-byte comparison.  
No external dependencies — pure stdlib (`pathlib`, `json`, `filecmp`, `shutil`).

## Error Handling

**specify command for each scenario**

| Scenario                               | Behaviour                                    |
|----------------------------------------|----------------------------------------------|
| Config not found on `run`              | Hard error with hint to run `init`           |
| Config version mismatch                | Hard error                                   |
| Project dir missing                    | Warn and skip (non-fatal)                    |
| Permission error on copy               | Caught per-file, logged, counted as `errors` |
| Missing `~/.claude/projects` on `init` | Warn, configure with empty project list      |

## Tests

New file: `tests/test_backup_sessions.py`

- `cmd_init`: creates config correctly; handles existing config (overwrite y/n); handles missing projects dir; writes
  correct JSON for all/none/selection; path decoding correct
- `cmd_run`: copies new files; skips unchanged; removes stale top-level files; removes stale payload files; prunes empty
  dirs; `--fast` uses stat comparison; `--status` exits early without copying; warns on missing project; loads
  shell-generated config (version compatibility)

## Bugs Fixed from Shell Scripts

1. **Path decode regex** (`init`): sed expression was wrong for Claude's single-dash encoding — replaced with correct
   Python decode logic
2. **JSON injection** (`init`): config was built via string concatenation — replaced with
   `json.dumps`
3. **Wrong filename in hint** (`init`): printed `backup.sh` instead of `backup-sessions.sh`
   — N/A in Python port (single entry point)
4. **Variable shadowing** (`run`): `src_file` reused for destination iteration — eliminated
5. **Counter increment** (`run`): `((N++)) || true` fragility — replaced with `N += 1`
6. **Default backup dir = script dir** (`run`): silently wrote into scripts/ — replaced with cwd default
