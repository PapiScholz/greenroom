# ADR-0001: Ship greenroom as a stdlib-only Python script driven by Claude Code hooks

- **Status:** accepted
- **Date:** 2026-10-10

## Context

Every installed skill puts its name and description in the context of every Claude Code session. With hundreds of skills that cost is large, and past a budget Claude Code drops descriptions. Hiding skills with `skillOverrides: "off"` also removes them from the user's `/` menu, and nothing tells the model they exist.

The tool that fixes this has to run on every session start and after every skill install, on Windows, macOS and Linux, on machines where the user may have nothing beyond Claude Code and a Python interpreter. It must never lose a skill and must be fully reversible.

## Decision

greenroom is one Python 3.9+ script using only the standard library, wired into Claude Code with a `SessionStart` hook (sync and print the skill map) and a `PostToolUse` hook on `Bash|PowerShell` (sync only after skill or plugin install commands). Members are hidden with `user-invocable-only`, never `off`, and every override changed is recorded in `state.json` so `install.py --uninstall` restores it.

## Alternatives considered

| Alternative | Why it was rejected |
|---|---|
| Claude Code plugin with its own skills (suggested — confirm) | `skillOverrides` does not apply to plugin skills, and a plugin cannot provide `/name` for every hidden user skill |
| Node/TypeScript CLI (suggested — confirm) | Adds a runtime and `node_modules` to a tool that only reads and writes JSON and Markdown |
| `skillOverrides: "off"` plus a manual index | Removes skills from the user's menu and depends on someone keeping the index current |
| Manual curation without hooks (suggested — confirm) | New skills would stay visible or get lost until someone remembered to file them |

## Consequences

- No install step beyond `python install.py`; nothing to keep updated except the script itself.
- greenroom depends on the hook payload format and the `skillOverrides` setting. A change in either breaks it, and the tests would not catch it because they simulate the payload.
- `settings.json` is rewritten as 2-space JSON; content is preserved, formatting may change.
- Classification is keyword-based and conservative: unclear skills stay visible and are listed as `pending`.
- The installed copy in `<claude dir>/greenroom/` must be refreshed by re-running `install.py` after pulling changes.

## Sources

- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code settings](https://code.claude.com/docs/en/settings)
- [Python `pathlib`](https://docs.python.org/3/library/pathlib.html)
