"""greenroom tests. Every test runs against a throwaway CLAUDE_CONFIG_DIR. Run: python -m unittest discover tests"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import greenroom as gr  # noqa: E402
import install  # noqa: E402


def skill(base: Path, folder: str, desc: str, name: str | None = None, dmi: bool = False) -> None:
    d = base / "skills" / folder
    d.mkdir(parents=True, exist_ok=True)
    extra = "disable-model-invocation: true\n" if dmi else ""
    (d / "SKILL.md").write_text(f"---\nname: {name or folder}\ndescription: {desc}\n{extra}---\nbody\n", encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp)
        (self.tmp / "greenroom").mkdir()
        shutil.copy(ROOT / "registry.example.json", self.tmp / "greenroom" / "registry.json")
        (self.tmp / "settings.json").write_text(json.dumps({"skillOverrides": {}}), encoding="utf-8")

    def tearDown(self):
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def overrides(self):
        return json.loads((self.tmp / "settings.json").read_text(encoding="utf-8")).get("skillOverrides", {})

    def registry(self):
        return json.loads((self.tmp / "greenroom" / "registry.json").read_text(encoding="utf-8"))

    def family(self, fid):
        return next(f for f in self.registry()["families"] if f["id"] == fid)

    def cli(self, args, stdin=""):
        """(exit code, stdout) of `greenroom.py <args>`; stdin is a str, or a dict sent as JSON."""
        out = io.StringIO()
        old = sys.stdin
        sys.stdin = io.StringIO(stdin if isinstance(stdin, str) else json.dumps(stdin))
        try:
            with redirect_stdout(out):
                code = gr.main(["greenroom.py", *args])
        finally:
            sys.stdin = old
        return code, out.getvalue()


class TestSync(Base):
    def test_new_skill_is_classified_hidden_and_listed_in_generated_gate(self):
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        notes = gr.sync()
        self.assertIn("gsap-scroll", self.family("motion")["skills"])
        self.assertEqual(self.overrides()["gsap-scroll"], "user-invocable-only")
        gate = (self.tmp / "skills" / "gate-motion" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`gsap-scroll`", gate)
        self.assertIn("name: gate-motion", gate)
        self.assertTrue(any(n.startswith("new -> motion") for n in notes))

    def test_never_off_preexisting_off_becomes_hide_and_check_flags_off(self):
        skill(self.tmp, "prisma-cli", "Prisma ORM CLI: migrate, generate, database schema and query reference.")
        (self.tmp / "settings.json").write_text(json.dumps({"skillOverrides": {"prisma-cli": "off", "other": "off"}}), encoding="utf-8")
        gr.sync()
        ov = self.overrides()
        self.assertNotIn("off", ov.values())
        self.assertEqual(ov["prisma-cli"], "user-invocable-only")
        # check() flags an "off" written behind greenroom's back
        (self.tmp / "settings.json").write_text(json.dumps({"skillOverrides": {**ov, "x": "off"}}), encoding="utf-8")
        problems, _ = gr.check()
        self.assertTrue(any("'off'" in p for p in problems))

    def test_keep_visible_is_never_hidden_and_its_override_is_removed(self):
        skill(self.tmp, "my-workflow", "Debug and review code with a git commit workflow for agent planning.")
        reg = self.registry()
        reg["keep_visible"] = ["my-workflow"]
        (self.tmp / "greenroom" / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
        (self.tmp / "settings.json").write_text(json.dumps({"skillOverrides": {"my-workflow": "off"}}), encoding="utf-8")
        gr.sync()
        self.assertNotIn("my-workflow", self.overrides())

    def test_deleted_skill_is_pruned_from_registry(self):
        skill(self.tmp, "vitest-patterns", "Vitest and Jest test patterns, flaky test fixes, e2e with Playwright.")
        gr.sync()
        self.assertIn("vitest-patterns", self.family("testing")["skills"])
        shutil.rmtree(self.tmp / "skills" / "vitest-patterns")
        notes = gr.sync()
        self.assertNotIn("vitest-patterns", self.family("testing")["skills"])
        self.assertTrue(any(n.startswith("removed from testing") for n in notes))

    def test_ambiguous_skill_goes_to_pending_hidden_behind_the_other_gate(self):
        skill(self.tmp, "weather", "Tells the weather forecast.")
        notes = gr.sync()
        self.assertEqual(self.registry()["pending"], ["weather"])  # the other gate itself is never classified
        self.assertEqual(self.overrides()["weather"], "user-invocable-only")
        gate = (self.tmp / "skills" / "gate-other" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`weather`", gate)
        self.assertNotIn("gate-other", self.overrides())
        self.assertEqual(gr.check(), ([], []))
        self.assertIn("`gate-other`", gr.session_text(self.tmp, notes))
        self.assertEqual(gr.sync(), [])

    def test_slash_only_skill_with_no_family_is_not_pending(self):
        skill(self.tmp, "weather", "Tells the weather forecast.", dmi=True)
        gr.sync()
        self.assertEqual(self.registry()["pending"], [])
        self.assertFalse((self.tmp / "skills" / "gate-other").exists())

    def test_other_gate_is_deleted_when_nothing_is_pending(self):
        skill(self.tmp, "weather", "Tells the weather forecast.")
        gr.sync()
        shutil.rmtree(self.tmp / "skills" / "weather")
        gr.sync()
        self.assertFalse((self.tmp / "skills" / "gate-other").exists())
        self.assertNotIn("gate-other", gr.session_text(self.tmp, []))

    def test_skill_with_disable_model_invocation_is_left_alone(self):
        skill(self.tmp, "manual-anim", "GSAP animation scroll motion helper.", dmi=True)
        gr.sync()
        self.assertNotIn("manual-anim", self.overrides())

    def test_override_uses_frontmatter_name_not_folder(self):
        skill(self.tmp, "folder-x", "GSAP scroll animation motion.", name="Pretty Name")
        gr.sync()
        self.assertEqual(self.overrides().get("Pretty Name"), "user-invocable-only")

    def test_close_race_is_flagged_in_the_sync_note(self):
        # motion: gsap, scroll, animat = 3; design: ui, layout = 2
        skill(self.tmp, "gsap-ui", "GSAP scroll animations for ui layout.")
        notes = gr.sync()
        self.assertIn("new -> motion (close: design): gsap-ui", notes)
        self.assertIn("gsap-ui", self.family("motion")["skills"])
        self.assertNotIn("gsap-ui", self.family("design")["skills"])

    def test_clear_win_has_no_close_note(self):
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        self.assertIn("new -> motion: gsap-scroll", gr.sync())

    def test_sync_is_idempotent(self):
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        gr.sync()
        self.assertEqual(gr.sync(), [])


class TestClassify(unittest.TestCase):
    REG = {"families": [
        {"id": "a", "keywords": ["orm", "ui", "gsap", "scroll", "animat", "easing", "three"]},
        {"id": "b", "keywords": ["performance", "latency", "react", "hooks"]},
    ]}

    def classify(self, folder, desc):
        return gr.classify({"name": folder, "desc": desc, "path": Path(folder) / "SKILL.md"}, self.REG)

    def test_keywords_match_whole_words_not_substrings(self):
        # substring matching found "orm" in performance/platforms and "ui" in build/guide: a 2-2 tie
        self.assertEqual(self.classify("tuner", "Performance tuning: build latency guide for platforms."), "b")

    def test_stems_and_common_suffixes_still_match(self):
        self.assertEqual(self.classify("x", "Animations with spring easing."), "a")
        self.assertEqual(self.classify("threejs-lights", "Lighting with scroll."), "a")

    def test_tie_is_broken_by_hits_in_the_name(self):
        self.assertEqual(self.classify("gsap-scroll-kit", "Use with React hooks."), "a")

    def test_tie_with_no_name_winner_is_none(self):
        self.assertIsNone(self.classify("kit", "GSAP scroll with React hooks."))

    def test_single_hit_is_not_enough(self):
        self.assertIsNone(self.classify("kit", "Uses GSAP."))

    def detail(self, folder, desc):
        return gr.classify_detail({"name": folder, "desc": desc, "path": Path(folder) / "SKILL.md"}, self.REG)

    def test_detail_names_the_runner_up_when_it_trails_by_one(self):
        # a: gsap, scroll, animat = 3; b: react, hooks = 2
        self.assertEqual(self.detail("x", "GSAP scroll animations for React hooks."), ("a", ["b"]))

    def test_detail_names_the_loser_of_a_tie_broken_by_the_name(self):
        self.assertEqual(self.detail("gsap-scroll-kit", "Use with React hooks."), ("a", ["b"]))

    def test_detail_has_no_runner_up_when_the_winner_leads_by_two_or_more(self):
        self.assertEqual(self.detail("x", "GSAP scroll animations with easing."), ("a", []))
        self.assertEqual(self.detail("x", "GSAP scroll animations with easing. React."), ("a", []))

    def test_detail_of_an_unclassified_skill_is_none_and_empty(self):
        self.assertEqual(self.detail("kit", "Uses GSAP."), (None, []))
        self.assertEqual(self.detail("kit", "GSAP scroll with React hooks."), (None, []))


class TestManualGate(Base):
    def setUp(self):
        super().setUp()
        reg = self.registry()
        fam = next(f for f in reg["families"] if f["id"] == "motion")
        fam["manual"] = True
        fam["skills"] = ["known-anim"]
        (self.tmp / "greenroom" / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
        skill(self.tmp, "gate-motion", "Hand-written motion gate.")
        (self.tmp / "skills" / "gate-motion" / "SKILL.md").write_text(
            "---\nname: gate-motion\ndescription: hand written\n---\nRead `known-anim` first.\n", encoding="utf-8")
        skill(self.tmp, "known-anim", "GSAP scroll animation motion.")

    def test_hand_written_gate_is_not_overwritten_and_new_skills_go_to_appendix(self):
        skill(self.tmp, "lottie-maker", "Create Lottie animation JSON with keyframe motion.")
        gr.sync()
        gate = (self.tmp / "skills" / "gate-motion" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("hand written", gate)
        appendix = (self.tmp / "skills" / "gate-motion" / "references" / "skills-added.md").read_text(encoding="utf-8")
        self.assertIn("`lottie-maker`", appendix)
        self.assertNotIn("`known-anim`", appendix)
        problems, orphans = gr.check()
        self.assertEqual((problems, orphans), ([], []))


class TestCheck(Base):
    def test_hidden_skill_without_family_is_an_orphan(self):
        skill(self.tmp, "lonely", "Nothing to match here.", dmi=True)  # dmi: sync leaves it out of every gate
        gr.sync()
        skill(self.tmp, "lonely", "Nothing to match here.")  # now hidden by hand, behind greenroom's back
        (self.tmp / "settings.json").write_text(json.dumps({"skillOverrides": {**self.overrides(), "lonely": "user-invocable-only"}}), encoding="utf-8")
        _, orphans = gr.check()
        self.assertEqual(orphans, ["lonely"])

    def test_hidden_gate_is_a_problem(self):
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        gr.sync()
        (self.tmp / "settings.json").write_text(json.dumps({"skillOverrides": {**self.overrides(), "gate-motion": "user-invocable-only"}}), encoding="utf-8")
        problems, _ = gr.check()
        self.assertTrue(any("gate is hidden" in p for p in problems))
        gr.sync()  # sync makes the gate visible again
        self.assertNotIn("gate-motion", self.overrides())


class TestDoubled(Base):
    """A keep_visible skill that is also in a family costs context twice: in the listing and in its gate."""

    def setUp(self):
        super().setUp()
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        skill(self.tmp, "manual-anim", "GSAP animation scroll motion helper.", dmi=True)
        reg = self.registry()
        reg["keep_visible"] = ["gsap-scroll", "manual-anim"]
        fam = next(f for f in reg["families"] if f["id"] == "motion")
        fam["skills"] = ["gsap-scroll", "manual-anim"]
        (self.tmp / "greenroom" / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
        gr.sync()

    def test_doubled_lists_model_invocable_overlap_and_skips_slash_only(self):
        self.assertEqual(gr.doubled(self.registry(), gr.inventory()), [("gsap-scroll", "motion")])

    def test_status_and_session_map_report_it(self):
        _, out = self.cli(["status"])
        self.assertIn("gsap-scroll (motion)", out)
        self.assertNotIn("manual-anim (motion)", out)
        self.assertIn("gsap-scroll (motion)", gr.session_text(self.tmp, []))

    def test_doubled_is_advice_not_a_check_failure(self):
        self.assertEqual(gr.check(), ([], []))


class TestHooks(Base):
    def test_session_prints_map_and_detects_repo_stack(self):
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        repo = self.tmp / "repo"
        repo.mkdir()
        (repo / "package.json").write_text(json.dumps({"dependencies": {"gsap": "3", "@playwright/test": "1"}}), encoding="utf-8")
        code, out = self.cli(["session"], {"cwd": str(repo)})
        self.assertEqual(code, 0)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("SKILL MAP", ctx)
        self.assertIn("`gate-motion` (gsap)", ctx)
        self.assertIn("`gate-testing` (@playwright/test)", ctx)
        self.assertIn("new -> motion: gsap-scroll", ctx)

    def test_map_and_generated_gates_carry_the_same_skill_rules(self):
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        _, out = self.cli(["session"], {"cwd": str(self.tmp)})
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(gr.RULES_LINE, ctx.splitlines())  # one line, through the gate or not
        gate = (self.tmp / "skills" / "gate-motion" / "SKILL.md").read_text(encoding="utf-8")
        for i, rule in enumerate(gr.SKILL_RULES, 1):
            self.assertIn(f"{i}. {rule[0].upper() + rule[1:]}.", gate)

    def test_session_detects_cdn_libraries_in_single_file_sites(self):
        repo = self.tmp / "site"
        (repo / "public").mkdir(parents=True)
        (repo / "public" / "index.html").write_text('<script src="https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js"></script>', encoding="utf-8")
        _, out = self.cli(["session"], {"cwd": str(repo)})
        self.assertIn("`gate-motion` (gsap)", json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_suggestion_only_in_git_repos_missing_the_files(self):
        reg = self.registry()
        reg["suggestions"] = [{"when_missing": ["README.md", "docs/adr"], "skill": "repo-baseline"}]
        (self.tmp / "greenroom" / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
        repo = self.tmp / "r"
        (repo / ".git").mkdir(parents=True)
        ctx = lambda: json.loads(self.cli(["session"], {"cwd": str(repo)})[1])["hookSpecificOutput"]["additionalContext"]
        self.assertIn("missing README.md, docs/adr: suggest `repo-baseline`", ctx())
        (repo / "README.md").write_text("x", encoding="utf-8")
        (repo / "docs" / "adr").mkdir(parents=True)
        self.assertNotIn("repo-baseline", ctx())
        shutil.rmtree(repo / ".git")
        (repo / "README.md").unlink()
        self.assertNotIn("repo-baseline", ctx())  # not a git repo: no suggestion

    def test_posttool_only_reacts_to_install_commands(self):
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        _, out = self.cli(["posttool"], {"tool_input": {"command": "npm test"}})
        self.assertEqual(out, "")
        self.assertNotIn("gsap-scroll", self.overrides())
        _, out = self.cli(["posttool"], {"tool_input": {"command": "npx skills add foo/bar -g -y"}})
        self.assertIn("new -> motion: gsap-scroll", out)
        self.assertEqual(self.overrides()["gsap-scroll"], "user-invocable-only")

    def test_install_regex(self):
        for cmd in ("npx skills add a/b", "npx -y skills remove x", "claude plugin install p@m", "npx skills update -g"):
            self.assertTrue(gr.INSTALL_RE.search(cmd), cmd)
        for cmd in ("npm run skills", "git add skills/", "ls skills"):
            self.assertFalse(gr.INSTALL_RE.search(cmd), cmd)


def jl(path: Path, *records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def tool(ts, name, inp, entrypoint="cli"):
    return {"type": "assistant", "timestamp": ts, "entrypoint": entrypoint,
            "message": {"role": "assistant", "content": [{"type": "tool_use", "name": name, "input": inp}]}}


def user(ts, text, entrypoint="cli"):
    return {"type": "user", "timestamp": ts, "entrypoint": entrypoint, "message": {"role": "user", "content": text}}


MAP = {"type": "attachment", "timestamp": "2026-10-11T10:00:00.000Z", "entrypoint": "cli",
       "attachment": {"hookName": "SessionStart:startup", "hookEvent": "SessionStart",
                      "stdout": "SKILL MAP (greenroom) — 2 skills are hidden"}}


class TestUsage(Base):
    def setUp(self):
        super().setUp()
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        skill(self.tmp, "lottie-maker", "Create Lottie animation JSON with keyframe motion.")
        skill(self.tmp, "prisma-cli", "Prisma ORM CLI: migrate, generate, database schema and query reference.")
        gr.sync()
        proj = self.tmp / "projects" / "C--repo"
        sk = str(self.tmp / "skills")
        # s1: map, enters gate-motion with Skill and reads gsap-scroll (Windows path); its subagent reads lottie-maker
        # (inside the gate the parent entered). Then enters gate-data by reading the gate's SKILL.md and reads prisma-cli.
        # Writing a file that mentions a SKILL.md path, or fetching a remote one, is no read.
        jl(proj / "s1.jsonl", MAP,
           tool("2026-10-11T10:01:00.000Z", "Skill", {"skill": "gate-motion"}),
           tool("2026-10-11T10:02:00.000Z", "Read", {"file_path": sk.replace("/", "\\") + "\\gsap-scroll\\SKILL.md"}),
           tool("2026-10-11T10:03:00.000Z", "Write", {"file_path": str(self.tmp / "handoff.md"), "content": sk + "/prisma-cli/SKILL.md"}),
           tool("2026-10-11T10:03:30.000Z", "Bash", {"command": "gh api repos/o/r/contents/skills/prisma-cli/SKILL.md"}),
           tool("2026-10-11T10:04:30.000Z", "Read", {"file_path": sk + "/gate-data/SKILL.md"}),
           tool("2026-10-11T10:05:00.000Z", "Read", {"file_path": sk + "/prisma-cli/SKILL.md"}))
        jl(proj / "s1" / "subagents" / "agent-a.jsonl",
           tool("2026-10-11T10:04:00.000Z", "Bash", {"command": f"cat {sk}/lottie-maker/SKILL.md"}))
        # s2: no map, reads prisma-cli entering no gate (the only read outside its gate), user types /prisma-cli,
        # enters gate-data (Skill, then its SKILL.md right after: one entry), then delegates lottie-maker to a subagent
        jl(proj / "s2.jsonl",
           tool("2026-10-12T09:00:00.000Z", "Read", {"file_path": sk + "/prisma-cli/SKILL.md"}),
           user("2026-10-12T09:01:00.000Z", "<command-message>prisma-cli</command-message>\n<command-name>/prisma-cli</command-name>"),
           tool("2026-10-12T09:02:00.000Z", "Skill", {"skill": "gate-data"}),
           tool("2026-10-12T09:02:30.000Z", "Read", {"file_path": sk + "/gate-data/SKILL.md"}),
           tool("2026-10-12T09:03:00.000Z", "Agent", {"prompt": f"Read {sk}/lottie-maker/SKILL.md and apply it"}))
        # sdk session: excluded from the denominator and from every count
        jl(proj / "s3.jsonl", tool("2026-10-12T09:00:00.000Z", "Skill", {"skill": "gate-motion"}, entrypoint="sdk-py"))
        # old session, before --since
        jl(proj / "s0.jsonl", tool("2026-10-01T09:00:00.000Z", "Skill", {"skill": "gate-motion"}))
        # started before --since and went on after it: could never have received the map, so it is not counted
        jl(proj / "s4.jsonl", user("2026-10-09T09:00:00.000Z", "hi"),
           tool("2026-10-11T09:00:00.000Z", "Skill", {"skill": "gate-motion"}),
           tool("2026-10-11T09:01:00.000Z", "Read", {"file_path": sk + "/prisma-cli/SKILL.md"}))

    def test_usage_counts_sessions_gates_reads_and_commands(self):
        r = gr.usage("2026-10-10")
        self.assertEqual(r["sessions"], {"interactive": 2, "with_map": 1, "non_interactive": {"sdk-py": 1}})
        self.assertEqual(r["gates"]["gate-motion"],
                         {"entries": 1, "via_skill": 1, "via_read": 0, "via_hidden_command": 0, "followed_by_read": 1})
        # s1 by reading the gate file (then prisma-cli); s2 by the user's /prisma-cli (hidden, data family),
        # with the Skill call and the gate file right after it folded into that one entry
        self.assertEqual(r["gates"]["gate-data"],
                         {"entries": 2, "via_skill": 0, "via_read": 1, "via_hidden_command": 1, "followed_by_read": 1})
        self.assertIn("gate-testing", r["gates_never_used"])
        self.assertNotIn("gate-motion", r["gates_never_used"])
        h = r["hidden_reads"]
        self.assertEqual((h["distinct"], h["total"], h["in_subagents"]), (3, 4, 1))  # Write, gh api, gate files: no reads
        self.assertEqual(h["delegated_to_subagent"], {"lottie-maker": 1})
        self.assertEqual(r["user_commands"], {"prisma-cli": 1})
        self.assertEqual(r["reads_outside_gate"], [
            {"skill": "prisma-cli", "family": "data", "gate": "gate-data", "subagent": False}])
        self.assertNotIn("motion", r["never_read"])

    def test_hidden_command_and_skill_load_enter_the_gate(self):
        sk = str(self.tmp / "skills")
        load = lambda ts, name: user(ts, [{"type": "text", "text": f"Base directory for this skill: {sk}\\{name}\n\n# body"}])
        jl(self.tmp / "projects" / "C--repo" / "s5.jsonl",
           # the user's /lottie-maker (hidden, motion family) enters gate-motion; its load is the same entry
           user("2026-10-13T09:00:00.000Z", "<command-message>lottie-maker</command-message>\n<command-name>/lottie-maker</command-name>"),
           load("2026-10-13T09:00:01.000Z", "lottie-maker"),
           tool("2026-10-13T09:01:00.000Z", "Read", {"file_path": sk + "/gsap-scroll/SKILL.md"}),
           # parallel Skill calls whose loads interleave: two entries, not four
           tool("2026-10-13T10:00:00.000Z", "Skill", {"skill": "gate-data"}),
           tool("2026-10-13T10:00:00.100Z", "Skill", {"skill": "gate-testing"}),
           load("2026-10-13T10:00:01.000Z", "gate-data"),
           load("2026-10-13T10:00:01.100Z", "gate-testing"),
           # a load with no call before it (e.g. the gate loaded on its own) is an entry too
           load("2026-10-13T11:00:00.000Z", "gate-infra"))
        r = gr.usage("2026-10-10")
        self.assertEqual(r["gates"]["gate-motion"]["entries"], 2)
        self.assertEqual(r["gates"]["gate-motion"]["via_hidden_command"], 1)
        self.assertEqual((r["gates"]["gate-data"]["entries"], r["gates"]["gate-testing"]["entries"]), (3, 1))
        self.assertEqual(r["gates"]["gate-infra"]["entries"], 1)
        self.assertEqual(r["user_commands"], {"lottie-maker": 1, "prisma-cli": 1})
        self.assertNotIn("gsap-scroll", [o["skill"] for o in r["reads_outside_gate"]])

    def test_skill_reads_only_count_local_reads(self):
        sk = str(self.tmp / "skills")
        rx = gr.local_skill_re()
        self.assertEqual(gr.skill_reads("Bash", {"command": f"head -50 {sk}/a-b/SKILL.md"}, rx), [("read", "a-b")])
        self.assertEqual(gr.skill_reads("PowerShell", {"command": f"Get-Content '{sk}\\a\\SKILL.md'"}, rx), [("read", "a")])
        self.assertEqual(gr.skill_reads("Bash", {"command": f"ls {sk}/a/SKILL.md"}, rx), [])  # not a read
        self.assertEqual(gr.skill_reads("Grep", {"path": f"{sk}/a/SKILL.md"}, rx), [])
        self.assertEqual(gr.skill_reads("Read", {"file_path": "/elsewhere/skills/a/SKILL.md"}, rx), [])

    def test_usage_all_includes_old_sessions(self):
        r = gr.usage(None, all_sessions=True)
        self.assertEqual(r["sessions"]["interactive"], 4)
        self.assertEqual(r["gates"]["gate-motion"]["entries"], 3)
        self.assertEqual((r["since"], r["since_source"]), (None, "--all"))

    def test_default_since_is_the_first_session_that_opened_with_the_map(self):
        # opened before the install, resumed after it: it got the map, but on resume, so it does not date the install
        resumed = dict(MAP, timestamp="2026-10-11T08:00:00.000Z",
                       attachment={"hookName": "SessionStart:resume", "hookEvent": "SessionStart",
                                   "stdout": "SKILL MAP (greenroom) — 2 skills are hidden"})
        jl(self.tmp / "projects" / "C--repo" / "s6.jsonl", user("2026-10-05T09:00:00.000Z", "hi"), resumed)
        r = gr.usage(None)
        self.assertEqual(r["since"], "2026-10-11T10:00:00.000Z")  # s1, the first one that opened with the map
        self.assertIn("first session that opened with the SKILL MAP (s1)", r["since_source"])
        self.assertEqual(r["sessions"], {"interactive": 2, "with_map": 1, "non_interactive": {"sdk-py": 1}})
        # with no map anywhere, the default falls back to every transcript and says so
        (self.tmp / "projects" / "C--repo" / "s1.jsonl").unlink()
        (self.tmp / "projects" / "C--repo" / "s6.jsonl").unlink()
        r = gr.usage(None)
        self.assertIsNone(r["since"])
        self.assertIn("no session got the SKILL MAP yet", r["since_source"])

    def test_session_hook_records_install_once_and_usage_uses_it(self):
        self.cli(["session"], {"cwd": str(self.tmp), "session_id": "s2"})
        state = json.loads((self.tmp / "greenroom" / "state.json").read_text(encoding="utf-8"))
        first = state["installed_at"]
        self.assertEqual(state["installed_session"], "s2")
        self.cli(["session"], {"cwd": str(self.tmp), "session_id": "s5"})
        state = json.loads((self.tmp / "greenroom" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual((state["installed_at"], state["installed_session"]), (first, "s2"))  # kept from the first time
        # the start is that session's first timestamp (it starts a moment before its hook runs), not the scan
        r = gr.usage(None)
        self.assertEqual(r["since"], "2026-10-12T09:00:00.000Z")
        self.assertIn("state.json installed_at (s2)", r["since_source"])
        self.assertEqual(r["sessions"]["interactive"], 1)

    def test_never_read_names_only_with_verbose(self):
        skill(self.tmp, "vitest-patterns", "Vitest and Jest test patterns, flaky test fixes, e2e with Playwright.")
        gr.sync()
        r = gr.usage("2026-10-10")
        self.assertIn("never read, by family (names with --verbose): testing 1", gr.usage_text(r))
        self.assertNotIn("vitest-patterns", gr.usage_text(r))
        self.assertIn("  testing (1): vitest-patterns", gr.usage_text(r, verbose=True))

    def test_usage_cli_text_and_json(self):
        code, out = self.cli(["usage", "--since", "2026-10-10"])
        self.assertEqual(code, 0)
        self.assertIn("2 interactive, 1 got the map (50%)", out)
        self.assertIn("sdk-py 1", out)
        self.assertEqual(json.loads(self.cli(["usage", "--json"])[1])["sessions"]["interactive"], 2)  # default: the install
        self.assertEqual(json.loads(self.cli(["usage", "--all", "--json"])[1])["sessions"]["interactive"], 4)
        with self.assertRaises(SystemExit):
            gr.usage("10/10/2026")


class TestPrompt(Base):
    def logged(self):
        p = self.tmp / "greenroom" / "prompts.jsonl"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.is_file() else []

    def test_keyword_hits_one_hit_at_word_start_short_keywords_whole_word(self):
        fams = self.registry()["families"]
        hits = gr.keyword_hits("Add a GSAP scroll animation and fix the flaky Playwright test", fams)
        self.assertEqual(hits["gate-motion"], ["animat", "gsap", "scroll"])
        self.assertEqual(hits["gate-testing"], ["test", "playwright", "flaky"])
        self.assertEqual(gr.keyword_hits("build the information page", fams), {})  # no "ui", no "orm"
        self.assertIn("gate-design", gr.keyword_hits("the UI looks off", fams))

    def test_prompt_logs_gates_but_not_the_text_and_prints_nothing(self):
        code, out = self.cli(["prompt"], {"prompt": "Run the Prisma migration on the schema, secret-word-xyz", "session_id": "s9", "cwd": "C:/repo"})
        self.assertEqual((code, out), (0, ""))
        [rec] = self.logged()
        self.assertEqual(rec["session_id"], "s9")
        self.assertEqual(rec["cwd"], "C:/repo")
        self.assertEqual(rec["gates"], {"gate-data": ["prisma", "migration", "schema"]})
        self.assertRegex(rec["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
        raw = (self.tmp / "greenroom" / "prompts.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("secret-word-xyz", raw)
        self.assertNotIn("Run the", raw)

    def test_prompt_never_fails(self):
        self.assertEqual(self.cli(["prompt"], "not json"), (0, ""))
        self.assertEqual(self.cli(["prompt"], {"prompt": 42}), (0, ""))
        (self.tmp / "greenroom" / "registry.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(self.cli(["prompt"], {"prompt": "gsap"}), (0, ""))
        self.assertEqual(self.logged(), [])

    def test_usage_crosses_prompts_with_the_transcripts(self):
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        gr.sync()
        sk = str(self.tmp / "skills")
        p = self.tmp / "greenroom" / "prompts.jsonl"
        rec = lambda ts, sid, gates: {"ts": ts, "session_id": sid, "cwd": "x", "gates": gates}
        p.write_text("".join(json.dumps(r) + "\n" for r in [
            rec("2026-10-11T10:00:00.000Z", "a", {"gate-motion": ["gsap"]}),     # entered before the next prompt
            rec("2026-10-11T10:10:00.000Z", "a", {}),                            # no match
            rec("2026-10-11T10:20:00.000Z", "a", {"gate-motion": ["scroll"]}),   # candidate, gate entered earlier
            rec("2026-10-11T10:30:00.000Z", "b", {"gate-testing": ["test"]}),    # candidate: entry comes after next prompt
            rec("2026-10-11T10:40:00.000Z", "b", {"gate-data": ["sql"]}),        # read of the gate file: entered
            rec("2026-10-11T10:50:00.000Z", "zz", {"gate-data": ["sql"]}),       # no transcript
        ]), encoding="utf-8")
        proj = self.tmp / "projects" / "C--repo"
        jl(proj / "a.jsonl", MAP,
           tool("2026-10-11T10:01:00.000Z", "Skill", {"skill": "gate-motion"}),
           tool("2026-10-11T10:02:00.000Z", "Read", {"file_path": sk + "/gsap-scroll/SKILL.md"}),
           tool("2026-10-11T10:21:00.000Z", "Bash", {"command": "npm run build"}))
        jl(proj / "b.jsonl", user("2026-10-11T10:30:00.500Z", "hi"),
           tool("2026-10-11T10:41:00.000Z", "Read", {"file_path": sk + "/gate-data/SKILL.md"}),
           tool("2026-10-11T10:42:00.000Z", "Skill", {"skill": "gate-testing"}))
        pr = gr.usage("2026-10-10")["prompts"]
        self.assertEqual((pr["logged"], pr["matched"], pr["entered"], pr["no_transcript"]), (6, 5, 2, 1))
        self.assertEqual(pr["gates"]["gate-motion"], {"matched": 2, "entered": 1, "candidates": 1, "keywords": {"scroll": 1}})
        self.assertEqual(pr["gates"]["gate-testing"]["candidates"], 1)
        # per-gate counts only include prompts that can be checked against a transcript
        self.assertEqual(pr["gates"]["gate-data"], {"matched": 1, "entered": 1, "candidates": 0, "keywords": {}})
        self.assertEqual([(c["session_id"], c["gate"], c["gate_entered_earlier"]) for c in pr["candidates"]],
                         [("b", "gate-testing", False), ("a", "gate-motion", True)])
        out = self.cli(["usage", "--since", "2026-10-10"])[1]
        self.assertIn("CANDIDATES, not confirmed failures", out)
        self.assertIn("a  2026-10-11T10:20:00  gate-motion  scroll  (gate entered earlier)", out)


class TestUninstall(Base):
    def test_uninstall_restores_every_override_and_removes_generated_gates(self):
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        skill(self.tmp, "prisma-cli", "Prisma ORM CLI: migrate, generate, database schema and query reference.")
        (self.tmp / "settings.json").write_text(json.dumps({"skillOverrides": {"prisma-cli": "off", "untouched": "on"}}), encoding="utf-8")
        settings = gr.read_json(self.tmp / "settings.json", {})
        install.add_hooks(settings)
        gr.write_json(self.tmp / "settings.json", settings)
        gr.sync()
        with redirect_stdout(io.StringIO()):
            install.uninstall()
        after = gr.read_json(self.tmp / "settings.json", {})
        self.assertEqual(after["skillOverrides"], {"prisma-cli": "off", "untouched": "on"})
        self.assertFalse((self.tmp / "skills" / "gate-motion").exists())
        self.assertTrue((self.tmp / "skills" / "gsap-scroll").exists())
        hooks = json.dumps(after.get("hooks", {}))
        self.assertNotIn("greenroom.py", hooks)

    def test_install_adds_the_three_hooks_once_and_uninstall_keeps_foreign_ones(self):
        foreign = {"hooks": [{"type": "command", "command": "other-tool"}]}
        settings = {"hooks": {"UserPromptSubmit": [foreign]}}
        install.add_hooks(settings)
        install.add_hooks(settings)  # idempotent
        for event, sub in (("SessionStart", "session"), ("PostToolUse", "posttool"), ("UserPromptSubmit", "prompt")):
            cmds = [h["command"] for g in settings["hooks"][event] for h in g["hooks"] if "greenroom.py" in h["command"]]
            self.assertEqual(len(cmds), 1, event)
            self.assertTrue(cmds[0].endswith(f" {sub}"), cmds[0])
        install.remove_hooks(settings)
        self.assertNotIn("greenroom.py", json.dumps(settings))
        self.assertEqual(settings["hooks"]["UserPromptSubmit"], [foreign])


if __name__ == "__main__":
    unittest.main()
