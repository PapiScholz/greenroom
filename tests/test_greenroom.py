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

    def test_ambiguous_skill_goes_to_pending_and_stays_visible(self):
        skill(self.tmp, "weather", "Tells the weather forecast.")
        gr.sync()
        self.assertIn("weather", self.registry()["pending"])
        self.assertNotIn("weather", self.overrides())

    def test_skill_with_disable_model_invocation_is_left_alone(self):
        skill(self.tmp, "manual-anim", "GSAP animation scroll motion helper.", dmi=True)
        gr.sync()
        self.assertNotIn("manual-anim", self.overrides())

    def test_override_uses_frontmatter_name_not_folder(self):
        skill(self.tmp, "folder-x", "GSAP scroll animation motion.", name="Pretty Name")
        gr.sync()
        self.assertEqual(self.overrides().get("Pretty Name"), "user-invocable-only")

    def test_sync_is_idempotent(self):
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        gr.sync()
        self.assertEqual(gr.sync(), [])


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
        skill(self.tmp, "lonely", "Nothing to match here.")
        gr.sync()
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


class TestHooks(Base):
    def run_cli(self, args, stdin):
        out = io.StringIO()
        old = sys.stdin
        sys.stdin = io.StringIO(json.dumps(stdin))
        try:
            with redirect_stdout(out):
                code = gr.main(["greenroom.py", *args])
        finally:
            sys.stdin = old
        return code, out.getvalue()

    def test_session_prints_map_and_detects_repo_stack(self):
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        repo = self.tmp / "repo"
        repo.mkdir()
        (repo / "package.json").write_text(json.dumps({"dependencies": {"gsap": "3", "@playwright/test": "1"}}), encoding="utf-8")
        code, out = self.run_cli(["session"], {"cwd": str(repo)})
        self.assertEqual(code, 0)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("SKILL MAP", ctx)
        self.assertIn("`gate-motion` (gsap)", ctx)
        self.assertIn("`gate-testing` (@playwright/test)", ctx)
        self.assertIn("new -> motion: gsap-scroll", ctx)

    def test_session_detects_cdn_libraries_in_single_file_sites(self):
        repo = self.tmp / "site"
        (repo / "public").mkdir(parents=True)
        (repo / "public" / "index.html").write_text('<script src="https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js"></script>', encoding="utf-8")
        _, out = self.run_cli(["session"], {"cwd": str(repo)})
        self.assertIn("`gate-motion` (gsap)", json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_suggestion_only_in_git_repos_missing_the_files(self):
        reg = self.registry()
        reg["suggestions"] = [{"when_missing": ["README.md", "docs/adr"], "skill": "repo-baseline"}]
        (self.tmp / "greenroom" / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
        repo = self.tmp / "r"
        (repo / ".git").mkdir(parents=True)
        ctx = lambda: json.loads(self.run_cli(["session"], {"cwd": str(repo)})[1])["hookSpecificOutput"]["additionalContext"]
        self.assertIn("missing README.md, docs/adr: suggest `repo-baseline`", ctx())
        (repo / "README.md").write_text("x", encoding="utf-8")
        (repo / "docs" / "adr").mkdir(parents=True)
        self.assertNotIn("repo-baseline", ctx())
        shutil.rmtree(repo / ".git")
        (repo / "README.md").unlink()
        self.assertNotIn("repo-baseline", ctx())  # not a git repo: no suggestion

    def test_posttool_only_reacts_to_install_commands(self):
        skill(self.tmp, "gsap-scroll", "Build GSAP scroll animations with ScrollTrigger and spring easing.")
        _, out = self.run_cli(["posttool"], {"tool_input": {"command": "npm test"}})
        self.assertEqual(out, "")
        self.assertNotIn("gsap-scroll", self.overrides())
        _, out = self.run_cli(["posttool"], {"tool_input": {"command": "npx skills add foo/bar -g -y"}})
        self.assertIn("new -> motion: gsap-scroll", out)
        self.assertEqual(self.overrides()["gsap-scroll"], "user-invocable-only")

    def test_install_regex(self):
        for cmd in ("npx skills add a/b", "npx -y skills remove x", "claude plugin install p@m", "npx skills update -g"):
            self.assertTrue(gr.INSTALL_RE.search(cmd), cmd)
        for cmd in ("npm run skills", "git add skills/", "ls skills"):
            self.assertFalse(gr.INSTALL_RE.search(cmd), cmd)


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


if __name__ == "__main__":
    unittest.main()
