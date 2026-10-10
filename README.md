# greenroom

**Keep hundreds of Claude Code skills off the context window without ever losing them.**

[Español](README.es.md)

In a theater, the *green room* is where performers wait off stage: not taking up the stage, but ready, and the stage manager knows who is there and calls them on when it's their cue. greenroom does that for [Claude Code skills](https://code.claude.com/docs/en/skills).

## The problem

Every skill you install puts its name and description in the context of **every** session. Past a few dozen skills that gets expensive, and past ~1% of the context window Claude Code starts [dropping descriptions](https://code.claude.com/docs/en/skills) of the skills you use least. The model then picks worse, or never finds the skill that would have done the job right.

The usual fixes make it worse:

- **Uninstalling** loses the skill.
- **`skillOverrides: "off"`** saves the context, but it also removes `/name` from *your* menu. And nothing tells the model the skill exists, so it improvises instead of using it.

## How greenroom fixes it

```
                 ┌──────────────── session start ────────────────┐
                 │  SKILL MAP: 250 skills are hidden but exist.  │
                 │  Gates: Motion → gate-motion · Data → …       │
                 │  This repo uses: gate-motion (gsap), …        │
                 └───────────────────────────────────────────────┘
                                      │
         visible (costs ~300 chars)   ▼
   gate-motion   gate-data   gate-testing   …   ← one per family
        │  reads SKILL.md from disk when a task needs it
        ▼
   gsap-core  r3f-shaders  remotion-render  …   ← hidden from the model,
                                                  still in your / menu
```

1. **Families and gates.** Skills are grouped into families (motion, design, infra, data, testing, backend, desktop, marketing, process; edit them freely). Each family has one visible **gate** skill that picks the members a task needs and reads their `SKILL.md` straight from disk.
2. **Hidden, never off.** Members get `skillOverrides: "user-invocable-only"`. That keeps them out of the model's context but leaves them in your `/` menu. greenroom never writes `"off"`, and it converts any `"off"` it finds.
3. **A map at session start.** A `SessionStart` hook injects a short map (~1.5k chars): what is hidden, which gates exist, and which gates **this repo** needs. It detects the stack from `package.json`, config files, and libraries loaded by CDN in single-file HTML sites.
4. **Zero maintenance.** On every session start, and right after any `skills add/remove` or `plugin install/uninstall`, greenroom:
   - classifies new skills by keyword;
   - hides them;
   - lists them in their gate;
   - prunes deleted ones.

   A skill with no clear family stays visible and the map flags it.
5. **No orphans.** `check` fails if any hidden skill is not reachable through a gate, if a gate is hidden, or if anything is `"off"`. The session map warns when that happens.

Measured on the author's machine (~300 skills), the skill listing went from ~30k to ~15k characters per session. Disabling two plugins whose skills were duplicated saved another ~11k.

## Install

Requires Python 3.9+ and Claude Code.

```bash
git clone https://github.com/PapiScholz/greenroom
cd greenroom
python install.py --dry-run     # preview: which family each of your skills would go to
python install.py               # install (asks before hiding anything)
```

The installer:
- copies `greenroom.py` to `~/.claude/greenroom/`;
- creates `~/.claude/greenroom/registry.json` from `registry.example.json`;
- backs up `settings.json`;
- adds two hooks (`SessionStart` and `PostToolUse` on `Bash|PowerShell`);
- runs the first sync.

Open a new session to see the map. `$CLAUDE_CONFIG_DIR` is honored.

Uninstall restores every override greenroom changed, removes the hooks and deletes the generated gates. Your skills are never touched.

```bash
python install.py --uninstall
```

## The registry

`~/.claude/greenroom/registry.json` is the single source of truth, and greenroom keeps it current. You only edit it to:

- **move a skill** to another family;
- **pin a skill** as always visible in `keep_visible`, for your own workflows you want auto-invoked;
- **place a `pending` skill** that had no clear family;
- **add a family:** `id`, `gate`, `title`, `summary`, `keywords`, `detect.deps`, `detect.files`;
- **write a gate yourself** with `"manual": true`. greenroom then never overwrites its `SKILL.md`. It only writes `references/skills-added.md` next to it with members your text doesn't mention yet; link that file from your gate.

`notes` is a list of extra lines for the session map, for things like "Cloudflare tools come from the claude.ai connector, not the plugin" or "load the orchestration skill before spawning subagents".

## Commands

```bash
python ~/.claude/greenroom/greenroom.py status    # families and counts
python ~/.claude/greenroom/greenroom.py sync      # what the hooks run
python ~/.claude/greenroom/greenroom.py check     # exit 1 on orphans or broken gates
```

## Limits

- **Plugin skills** are not affected by `skillOverrides` ([docs](https://code.claude.com/docs/en/skills)). Manage them with `/plugin`, per project if needed (`enabledPlugins` in `<repo>/.claude/settings.json`). A gate can still read a disabled plugin's `SKILL.md` from the plugin cache.
- **Classification** is keyword-based and conservative: it needs at least 2 hits and a clear winner, otherwise the skill stays visible as `pending`.
- **Formatting:** greenroom rewrites `settings.json` with 2-space JSON. Content is preserved, formatting may change.
- **Project skills** (`<repo>/.claude/skills`) are not classified. Overrides apply by name, so a hidden user skill also hides a project skill with the same name.

## Tests

```bash
python -m unittest discover tests
```

Every test runs in a throwaway `CLAUDE_CONFIG_DIR`. Mutations were checked: writing `"off"`, disabling classification or matching every command each turn tests red.

## License

MIT
