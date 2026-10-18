#!/usr/bin/env python3
"""Install, preview or uninstall greenroom for Claude Code.

  python install.py --dry-run          show which family each installed skill would go to; writes nothing
  python install.py                    install (asks before hiding anything)
  python install.py --yes              install without asking
  python install.py --registry FILE    start from your own registry instead of registry.example.json
  python install.py --uninstall        remove hooks, restore every override greenroom changed, delete generated gates

The claude dir is $CLAUDE_CONFIG_DIR or ~/.claude. settings.json is backed up whenever a run changes it.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import greenroom as gr  # noqa: E402


def hook_cmd(sub: str) -> str:
    script = gr.paths()["data"] / "greenroom.py"
    return f'"{sys.executable}" -X utf8 "{script}" {sub}'


def settings_snapshot() -> str | None:
    """The text of settings.json before a run, or None when the file does not exist."""
    s = gr.paths()["settings"]
    return s.read_text(encoding="utf-8") if s.is_file() else None


def backup_settings(before: str | None) -> str:
    """Write the pre-run text to settings.json.bak-<stamp>-greenroom, only if the run changed the file: a no-op
    reinstall leaves no backup behind. Returns the line to print."""
    s = gr.paths()["settings"]
    if before is None:
        return "settings.json created"
    if s.read_text(encoding="utf-8") == before:
        return "settings unchanged, no backup"
    dst = s.with_name(f"settings.json.bak-{time.strftime('%Y%m%d-%H%M%S')}-greenroom")
    dst.write_text(before, encoding="utf-8", newline="")
    return f"settings backup: {dst}"


def has_hook(groups: list, marker: str) -> bool:
    return any(marker in h.get("command", "") for g in groups for h in g.get("hooks", []))


def add_hooks(settings: dict) -> None:
    hooks = settings.setdefault("hooks", {})
    ss = hooks.setdefault("SessionStart", [])
    if not has_hook(ss, "greenroom.py"):
        ss.append({"hooks": [{"type": "command", "command": hook_cmd("session"), "timeout": 15}]})
    pt = hooks.setdefault("PostToolUse", [])
    if not has_hook(pt, "greenroom.py"):
        pt.append({"matcher": "Bash|PowerShell", "hooks": [{"type": "command", "command": hook_cmd("posttool"), "timeout": 30}]})
    # Logs which gates each prompt matches (never the text) so `usage` can find possible improvisations. Prints nothing.
    up = hooks.setdefault("UserPromptSubmit", [])
    if not has_hook(up, "greenroom.py"):
        up.append({"hooks": [{"type": "command", "command": hook_cmd("prompt"), "timeout": 5}]})


def remove_hooks(settings: dict) -> None:
    for event in ("SessionStart", "PostToolUse", "UserPromptSubmit"):
        groups = settings.get("hooks", {}).get(event, [])
        kept = []
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if "greenroom.py" not in h.get("command", "")]
            if g["hooks"]:
                kept.append(g)
        if event in settings.get("hooks", {}):
            settings["hooks"][event] = kept


def dry_run(reg: dict) -> None:
    inv = gr.inventory()
    known = {s for f in reg["families"] for s in f["skills"]} | set(reg.get("keep_visible", []))
    by = {}
    for d, fm in inv.items():
        fid = next((f["id"] for f in reg["families"] if d in f["skills"]), None) if d in known else gr.classify(fm, reg)
        if d in reg.get("keep_visible", []):
            fid = "(keep_visible)"
        by.setdefault(fid or "(no family: stays visible)", []).append(d)
    for k in sorted(by, key=str):
        print(f"\n{k} ({len(by[k])})\n  " + ", ".join(by[k]))


def install(args) -> int:
    p = gr.paths()
    src_reg = Path(args.registry) if args.registry else HERE / "registry.example.json"
    reg = gr.read_json(p["registry"], None) or gr.read_json(src_reg, None)
    if reg is None:
        print(f"cannot read registry {src_reg}")
        return 1
    reg.setdefault("keep_visible", [])
    if args.dry_run:
        dry_run(reg)
        return 0
    if not args.yes:
        dry_run(reg)
        ans = input("\nHide every skill listed under a family (they stay in your / menu)? [y/N] ").strip().lower()
        if ans not in ("y", "yes", "s", "si", "sí"):
            print("nothing changed")
            return 1
    p["data"].mkdir(parents=True, exist_ok=True)
    if not p["registry"].is_file():
        shutil.copy2(src_reg, p["registry"])
        print(f"registry created from {src_reg}")
    shutil.copy2(HERE / "greenroom.py", p["data"] / "greenroom.py")
    before = settings_snapshot()
    settings = gr.read_json(p["settings"], {})
    add_hooks(settings)
    gr.write_json(p["settings"], settings)
    notes = gr.sync()
    problems, orphans = gr.check()
    print(backup_settings(before))
    print(f"{len(notes)} changes; check: {'OK' if not (problems or orphans) else 'FAIL'}")
    for x in problems + [f"orphan: {o}" for o in orphans]:
        print("  ", x)
    print("Open a new Claude Code session to see the map.")
    return 0


def uninstall() -> int:
    p = gr.paths()
    before = settings_snapshot()
    settings = gr.read_json(p["settings"], {})
    remove_hooks(settings)
    state = gr.read_json(p["state"], {"managed_overrides": {}})
    ov = settings.setdefault("skillOverrides", {})
    for name, previous in state.get("managed_overrides", {}).items():
        if previous is None:
            ov.pop(name, None)
        else:
            ov[name] = previous
    gr.write_json(p["settings"], settings)
    removed = []
    if p["skills"].is_dir():
        for d in p["skills"].iterdir():
            f = d / "SKILL.md"
            if f.is_file() and "GENERATED by greenroom" in f.read_text(encoding="utf-8", errors="replace"):
                shutil.rmtree(d)
                removed.append(d.name)
    gr.write_json(p["state"], {"managed_overrides": {}})
    print(f"hooks removed, {len(state.get('managed_overrides', {}))} overrides restored, generated gates deleted: {', '.join(removed) or 'none'}")
    print(f"{backup_settings(before)}; registry kept at {p['registry']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--registry")
    ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()
    return uninstall() if args.uninstall else install(args)


if __name__ == "__main__":
    sys.exit(main())
