import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("upstream", Path(__file__).parents[1] / "scripts/upstream.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BuildInputsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.builder = self.root / "builder"
        self.source = self.root / "source"
        self.builder.mkdir()
        self.source.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.write("apps/mobile/app.config.ts", "mobile")
        self.write("packages/client-runtime/src/connection.ts", "shared")
        self.write("apps/web/src/app.ts", "web")
        self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.source)

    def write(self, path, contents):
        target = self.source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "Change")

    def fingerprint(self):
        return module.input_fingerprint(self.source, self.builder)

    def test_web_only_nightly_does_not_rebuild(self):
        before = self.fingerprint()
        self.write("apps/web/src/app.ts", "new web")
        self.commit()
        self.assertEqual(before, self.fingerprint())

    def test_mobile_and_shared_changes_rebuild(self):
        for path in ["apps/mobile/app.config.ts", "packages/client-runtime/src/connection.ts"]:
            before = self.fingerprint()
            self.write(path, "changed")
            self.commit()
            self.assertNotEqual(before, self.fingerprint())

    def test_deleted_mobile_file_rebuilds(self):
        self.write("apps/mobile/src/screen.ts", "screen")
        self.commit()
        before = self.fingerprint()
        (self.source / "apps/mobile/src/screen.ts").unlink()
        self.commit()
        self.assertNotEqual(before, self.fingerprint())

    def test_builder_recipe_change_rebuilds(self):
        before = self.fingerprint()
        (self.builder / "build-config.json").write_text('{"architecture":"arm64"}')
        self.assertNotEqual(before, self.fingerprint())

    def test_unchanged_check_does_not_fetch_source_tree(self):
        plan = {"upstream": "pingdotgg/t3code", "upstream_tag": "v0.0.46-nightly.20261003.2623",
                "upstream_sha": "a" * 40}
        (self.builder / "build-plan.json").write_text(json.dumps(plan))
        source = "b" * 64
        previous = {"upstream_sha": plan["upstream_sha"], "source_fingerprint": source,
                    "input_fingerprint": hashlib.sha256((source + module.recipe_fingerprint(self.builder)).encode()).hexdigest()}
        env = {"GITHUB_REPOSITORY": "owner/builds", "GITHUB_RUN_NUMBER": "3", "FORCE_BUILD": "false",
               "GITHUB_OUTPUT": str(self.root / "outputs"), "GITHUB_STEP_SUMMARY": str(self.root / "summary")}
        release = {"assets": [{"name": "build-info.json", "browser_download_url": "https://example.com/info"}]}
        with patch.object(module, "ROOT", self.builder), patch.object(module, "api", return_value=release) as api, \
             patch.object(module, "recipe_fingerprint", return_value=module.recipe_fingerprint(self.builder)), \
             patch.object(module, "urlopen", return_value=io.StringIO(json.dumps(previous))), patch.dict(os.environ, env):
            module.check()
        api.assert_called_once_with("repos/owner/builds/releases/latest", missing_ok=True)
        self.assertIn("needed=false", (self.root / "outputs").read_text())

    def test_truncated_tree_is_not_mistaken_for_a_complete_snapshot(self):
        with self.assertRaisesRegex(RuntimeError, "truncated"):
            module.selected_tree({"truncated": True, "tree": []})

    def test_stable_gate_skips_unchanged_and_allows_new_or_manual_releases(self):
        stable = {"tag_name": "v0.0.45", "draft": False, "prerelease": False,
                  "html_url": "https://example.com/stable", "published_at": "2026-10-02T18:17:31Z"}
        (self.builder / "build-config.json").write_text('{"upstream":"pingdotgg/t3code"}')
        for previous, force, eligible in [
            ({"stable_trigger_tag": "v0.0.45"}, "false", "false"),
            ({"stable_trigger_tag": "v0.0.44"}, "false", "true"),
            ({}, "false", "true"),
            ({"stable_trigger_tag": "v0.0.45"}, "true", "true"),
        ]:
            with self.subTest(previous=previous, force=force):
                outputs = self.root / "gate-outputs"
                outputs.write_text("")
                env = {"FORCE_BUILD": force, "GITHUB_OUTPUT": str(outputs),
                       "GITHUB_STEP_SUMMARY": str(self.root / "gate-summary")}
                with patch.object(module, "ROOT", self.builder), patch.object(module, "api", return_value=stable) as api, \
                     patch.object(module, "latest_build", return_value=previous), patch.dict(os.environ, env):
                    module.gate()
                self.assertIn(f"eligible={eligible}", outputs.read_text())
                # No nightly enumeration, source checkout or source-tree requests at the gate.
                api.assert_called_once_with("repos/pingdotgg/t3code/releases/latest")

    def test_new_stable_builds_even_when_mobile_inputs_are_identical(self):
        source = "b" * 64
        fingerprint = hashlib.sha256((source + module.recipe_fingerprint(self.builder)).encode()).hexdigest()
        plan = {"upstream": "pingdotgg/t3code", "upstream_tag": "v0.0.46-nightly.20261003.2623",
                "upstream_sha": "a" * 40, "stable_trigger_tag": "v0.0.45"}
        previous = {"upstream_sha": plan["upstream_sha"], "source_fingerprint": source,
                    "input_fingerprint": fingerprint, "stable_trigger_tag": "v0.0.44"}
        (self.builder / "build-plan.json").write_text(json.dumps(plan))
        outputs = self.root / "stable-outputs"
        env = {"GITHUB_RUN_NUMBER": "8", "FORCE_BUILD": "false", "GITHUB_OUTPUT": str(outputs),
               "GITHUB_STEP_SUMMARY": str(self.root / "stable-summary")}
        with patch.object(module, "ROOT", self.builder), patch.object(module, "latest_build", return_value=previous), \
             patch.object(module, "recipe_fingerprint", return_value=module.recipe_fingerprint(self.builder)), \
             patch.object(module, "api") as api, patch.dict(os.environ, env):
            module.check()
        self.assertIn("needed=true", outputs.read_text())
        api.assert_not_called()
