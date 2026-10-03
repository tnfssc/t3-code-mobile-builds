import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

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
