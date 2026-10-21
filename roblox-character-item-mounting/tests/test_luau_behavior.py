"""Offline behavior tests. Optional Lune must be installed already; never downloads.

Set LUNE_BIN to an executable path, or put lune on PATH. Without it these tests
are explicitly skipped, not reported as Luau behavior passing. No Studio/account
or network is contacted. Lune @lune/roblox supplies real CFrame mathematics;
Instance/Players/Humanoid interactions are mocks, not engine acceptance.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest


HERE = Path(__file__).resolve().parent
LUNE = os.environ.get("LUNE_BIN") or shutil.which("lune")


@unittest.skipUnless(LUNE, "Lune unavailable; set LUNE_BIN for offline Luau behavior tests")
class LuauBehaviorTests(unittest.TestCase):
    def run_fixture(self, fixture):
        result = subprocess.run(
            [LUNE, "run", str(HERE / fixture)], cwd=HERE,
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_mount_core_behavior(self):
        output = self.run_fixture("mount_core_behavior.luau")
        self.assertIn("MOUNT_CORE_BEHAVIOR_OK", output)

    def test_luau_sources_compile(self):
        output = self.run_fixture("compile_sources.luau")
        self.assertIn("ALL_LUAU_SOURCES_COMPILE_OK", output)


if __name__ == "__main__":
    unittest.main()
