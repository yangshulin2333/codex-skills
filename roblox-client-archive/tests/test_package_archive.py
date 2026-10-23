"""Offline fixtures only: no Roblox process, game code, or network."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("package_archive", Path(__file__).resolve().parents[1] / "scripts" / "package_archive.py")
archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="archive-package-test-")
        self.root = Path(self.temp.name)
        self.source = self.root / "reviewed"
        self.source.mkdir()
        (self.source / "snapshot").mkdir()
        (self.source / "README.md").write_text("# Client snapshot\nNot a full game or an offline guarantee.\n", encoding="utf-8")
        (self.source / "metadata.json").write_text('{"placeId":123,"scope":"client-visible"}', encoding="utf-8")
        (self.source / "snapshot" / "scene.rbxlx").write_bytes(b'<roblox version="4"><Item class="Folder" referent="fixture"/></roblox>')
        (self.source / "texture.bin").write_bytes(b"fixture texture\x00\x01")
        self.zip = self.root / "project.zip"

    def tearDown(self):
        self.temp.cleanup()

    def create(self, **kwargs):
        return archive.package_archive(self.source, self.zip, **kwargs)

    def rewrite(self, changes=None, extra=None):
        changes = changes or {}
        with zipfile.ZipFile(self.zip) as handle:
            entries = [(item.filename, changes.get(item.filename, handle.read(item.filename))) for item in handle.infolist()]
        self.zip.unlink()
        with zipfile.ZipFile(self.zip, "x", compression=zipfile.ZIP_STORED) as handle:
            for name, payload in entries:
                handle.writestr(name, payload)
            for name, payload in extra or []:
                handle.writestr(name, payload)

    def test_success_preserves_original_xml_and_hashes_every_entry(self):
        before = archive.inventory(self.source)
        result = self.create()
        self.assertTrue(result["sourceUnchanged"])
        self.assertEqual(before, archive.inventory(self.source))
        with zipfile.ZipFile(self.zip) as handle:
            self.assertIn("snapshot/scene.rbxlx", handle.namelist())
            self.assertNotIn(archive.LAUNCHER, handle.namelist())
            checks = json.loads(handle.read(archive.MANIFEST))
            self.assertEqual(checks["selfExcluded"], [archive.MANIFEST])
            self.assertEqual(len(checks["files"]) + 1, len(handle.namelist()))
        self.assertEqual(result["zipSha256"], archive.file_digest(self.zip)["sha256"])
        report = json.loads(Path(result["verification"]).read_text(encoding="utf-8"))
        self.assertEqual(report["sourceBeforeInventorySha256"], report["sourceAfterInventorySha256"])

    def test_verify_existing_is_read_only_for_zip_and_source(self):
        self.create()
        digest = archive.file_digest(self.zip)
        result = archive.package_archive(self.source, verify_existing=self.zip)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(digest, archive.file_digest(self.zip))

    def test_tampered_payload_fails_sha(self):
        self.create()
        self.rewrite({"texture.bin": b"same size? BAD"})
        with self.assertRaisesRegex(archive.ArchiveError, "(size|SHA-256) mismatch"):
            archive.package_archive(self.source, verify_existing=self.zip)

    def test_changed_manifest_cannot_disguise_changed_source_payload(self):
        self.create()
        with zipfile.ZipFile(self.zip) as handle:
            manifest = json.loads(handle.read(archive.MANIFEST))
        for entry in manifest["files"]:
            if entry["path"] == "texture.bin":
                entry.update(bytes=3, sha256=archive.sha_bytes(b"bad"))
        self.rewrite({"texture.bin": b"bad", archive.MANIFEST: archive.json_bytes(manifest)})
        with self.assertRaisesRegex(archive.ArchiveError, "differ from source"):
            archive.package_archive(self.source, verify_existing=self.zip)

    def test_crc_corruption_detected(self):
        self.create()
        self.rewrite()
        with zipfile.ZipFile(self.zip) as handle:
            item = handle.getinfo("texture.bin")
            offset = item.header_offset
        with self.zip.open("r+b") as handle:
            handle.seek(offset + 26)
            lengths = handle.read(4)
            payload_offset = offset + 30 + int.from_bytes(lengths[:2], "little") + int.from_bytes(lengths[2:], "little")
            handle.seek(payload_offset)
            byte = handle.read(1)
            handle.seek(payload_offset)
            handle.write(bytes([byte[0] ^ 1]))
        with self.assertRaisesRegex(archive.ArchiveError, "CRC"):
            archive.package_archive(self.source, verify_existing=self.zip)

    def test_unexpected_entry_detected(self):
        self.create()
        self.rewrite(extra=[("unexpected.bin", b"bad")])
        with self.assertRaisesRegex(archive.ArchiveError, "entry set mismatch"):
            archive.package_archive(self.source, verify_existing=self.zip)

    def test_unsafe_zip_path_detected(self):
        self.create()
        self.rewrite(extra=[("../escape", b"bad")])
        with self.assertRaisesRegex(archive.ArchiveError, "Unsafe"):
            archive.package_archive(self.source, verify_existing=self.zip)

    def test_source_output_overlap_and_overwrite_refused(self):
        with self.assertRaisesRegex(archive.ArchiveError, "contain"):
            archive.package_archive(self.source, self.source / "archive.zip")
        self.zip.write_bytes(b"keep")
        with self.assertRaisesRegex(archive.ArchiveError, "overwrite"):
            self.create()
        self.assertEqual(self.zip.read_bytes(), b"keep")

    def test_review_required_for_cache_and_incomplete_items(self):
        for name in ("unfinished.lock", "unfinished.partial", "unfinished.tmp", "__pycache__", ".git"):
            with self.subTest(name=name):
                path = self.source / name
                path.mkdir() if name in ("__pycache__", ".git") else path.write_bytes(b"unfinished")
                try:
                    with self.assertRaisesRegex(archive.ArchiveError, "Unfinished/local-only"):
                        self.create()
                finally:
                    path.rmdir() if path.is_dir() else path.unlink()

    def test_missing_readme_and_metadata_refused(self):
        (self.source / "README.md").unlink()
        with self.assertRaisesRegex(archive.ArchiveError, "README"):
            self.create()
        (self.source / "README.md").write_text("Scope", encoding="utf-8")
        (self.source / "metadata.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(archive.ArchiveError, "nonempty"):
            self.create()

    def test_source_symlink_refused(self):
        link = self.source / "link.bin"
        try:
            link.symlink_to(self.source / "texture.bin")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"OS cannot create a fixture symlink: {exc}")
        with self.assertRaisesRegex(archive.ArchiveError, "Symbolic link/reparse"):
            self.create()

    def test_windows_reparse_attribute_is_rejected(self):
        info = mock.Mock(st_mode=0o100644, st_file_attributes=0x400)
        self.assertTrue(archive.is_reparse(info))

    def test_zip_reparse_attribute_rejected(self):
        self.create()
        with zipfile.ZipFile(self.zip) as handle:
            entries = [(item.filename, handle.read(item.filename)) for item in handle.infolist()]
        self.zip.unlink()
        with zipfile.ZipFile(self.zip, "x") as handle:
            for name, payload in entries:
                info = zipfile.ZipInfo(name)
                if name == "texture.bin":
                    info.external_attr = (0o100644 << 16) | 0x400
                handle.writestr(info, payload)
        with self.assertRaisesRegex(archive.ArchiveError, "Symlink/encrypted"):
            archive.package_archive(self.source, verify_existing=self.zip)

    def test_cli_json_contract(self):
        result = subprocess.run([sys.executable, "-B", str(Path(SPEC.origin)), "--source", str(self.source), "--output", str(self.zip)], capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "passed")

    def test_source_change_during_run_is_recorded_failure(self):
        actual_verify = archive.verify_archive
        def changing_source(*args, **kwargs):
            result = actual_verify(*args, **kwargs)
            (self.source / "texture.bin").write_bytes(b"changed after ZIP validation")
            return result
        with mock.patch.object(archive, "verify_archive", changing_source):
            with self.assertRaisesRegex(archive.ArchiveError, "Source changed"):
                self.create()
        report = json.loads(Path(str(self.zip) + ".verification.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["sourceUnchanged"])

    def test_xml_is_never_renamed_to_native_scene(self):
        with self.assertRaisesRegex(archive.ArchiveError, "native .rbxl"):
            self.create(create_launcher=True)

    def test_native_scene_launcher_and_checkonly(self):
        (self.source / "native.rbxl").write_bytes(b"<roblox!fixture-native-header")
        result = self.create(native_scene_relative_path="native.rbxl", create_launcher=True)
        self.assertTrue(result["launcherCreated"])
        with zipfile.ZipFile(self.zip) as handle:
            payload = handle.read(archive.LAUNCHER)
            self.assertIn(b"STUDIO_EXE", payload)
            self.assertIn(b"CheckOnly: no Studio process started", payload)
            self.assertNotIn(b"ExecutionPolicy", payload)
            extracted = self.root / "extracted"
            handle.extractall(extracted)
        if os.name == "nt":
            env = dict(os.environ, STUDIO_EXE=sys.executable)
            run = subprocess.run(["cmd.exe", "/d", "/c", str(extracted / archive.LAUNCHER), "-CheckOnly"], env=env, capture_output=True, timeout=30)
            output = (run.stdout + run.stderr).decode("utf-8", errors="replace")
            self.assertEqual(run.returncode, 0, output)
            self.assertIn("CheckOnly: no Studio process started", output)

    def test_explicit_xml_launcher_targets_reconstructed_copy_and_reverifies(self):
        target = "snapshot/scene_with_luau.rbxlx"
        (self.source / target).write_bytes(b'<roblox version="4"><Item class="Folder" referent="recovered"/></roblox>')
        result = self.create(scene_relative_path="snapshot/scene.rbxlx",
                             launcher_scene_relative_path=target, create_launcher=True)
        self.assertEqual(result["selection"], ["snapshot/scene.rbxlx", "metadata.json", None])
        self.assertEqual(result["launcherSceneRelativePath"], target)
        with zipfile.ZipFile(self.zip) as handle:
            metadata = json.loads(handle.read(archive.METADATA))
            self.assertEqual(metadata["launcherSceneRelativePath"], target)
            self.assertTrue(metadata["launcherSceneExplicit"])
            self.assertIn(b"$scene=ArchivePath 'snapshot/scene_with_luau.rbxlx'", handle.read(archive.LAUNCHER))
            self.assertEqual(handle.read("snapshot/scene.rbxlx"), (self.source / "snapshot/scene.rbxlx").read_bytes())
        reread = archive.package_archive(self.source, verify_existing=self.zip,
                                         scene_relative_path="snapshot/scene.rbxlx",
                                         launcher_scene_relative_path=target)
        self.assertEqual(reread["launcherSceneRelativePath"], target)
        with self.assertRaisesRegex(archive.ArchiveError, "Launcher scene selection mismatch"):
            archive.package_archive(self.source, verify_existing=self.zip,
                                    verification_output=self.root / "mismatch.json",
                                    scene_relative_path="snapshot/scene.rbxlx",
                                    launcher_scene_relative_path="snapshot/scene.rbxlx")

    def test_explicit_launcher_is_not_silently_ignored_without_creation_flag(self):
        with self.assertRaisesRegex(archive.ArchiveError, "requires --create-launcher"):
            self.create(launcher_scene_relative_path="snapshot/scene.rbxlx")

    def test_native_alias_stays_native_only_and_conflicting_aliases_fail(self):
        with self.assertRaisesRegex(archive.ArchiveError, "native scene extension"):
            self.create(native_scene_relative_path="snapshot/scene.rbxlx", create_launcher=True)
        (self.source / "native.rbxl").write_bytes(b"<roblox!fixture-native-header")
        with self.assertRaisesRegex(archive.ArchiveError, "must select the same file"):
            self.create(native_scene_relative_path="native.rbxl", create_launcher=True,
                        launcher_scene_relative_path="snapshot/scene.rbxlx")

    def test_explicit_native_launcher_requires_matching_native_signature(self):
        path = self.source / "native.rbxl"
        path.write_bytes((self.source / "snapshot/scene.rbxlx").read_bytes())
        with self.assertRaisesRegex(archive.ArchiveError, "native Roblox signature"):
            self.create(create_launcher=True, launcher_scene_relative_path="native.rbxl")
        path.write_bytes(b"<roblox!\x89\xff\r\n\x1a\n" + bytes(18))
        result = self.create(create_launcher=True, launcher_scene_relative_path="native.rbxl")
        self.assertEqual(result["launcherSceneRelativePath"], "native.rbxl")

    def test_explicit_xml_launcher_rejects_malformed_nonroblox_and_entity_inputs(self):
        path = self.source / "snapshot/scene.rbxlx"
        fixtures = ((b"<roblox!not-xml", "Invalid launcher"),
                    (b'<roblox version="4"><Item></roblox>', "Invalid launcher"),
                    (b'<notroblox version="4"/>', "roblox root"),
                    (b'<roblox version="3"/>', "version 4"),
                    (b'<!DOCTYPE roblox [<!ENTITY value "x">]><roblox version="4">&value;</roblox>', "DTD/entities"))
        for data, error in fixtures:
            with self.subTest(data=data):
                path.write_bytes(data)
                with self.assertRaisesRegex(archive.ArchiveError, error):
                    self.create(create_launcher=True, launcher_scene_relative_path="snapshot/scene.rbxlx")
                self.assertFalse(self.zip.exists())

    def test_explicit_launcher_rejects_missing_wrong_extension_traversal_and_controls(self):
        for target, error in (("snapshot/missing.rbxlx", "exactly one existing"),
                              ("texture.bin", "extension"), ("../scene.rbxlx", "Unsafe"),
                              ("snapshot/scene\x7f.rbxlx", "Non-portable"),
                              ("snapshot/scene\u2028.rbxlx", "Non-portable"),
                              ("snapshot/scene\n.rbxlx", "Non-portable")):
            with self.subTest(target=target):
                with self.assertRaisesRegex(archive.ArchiveError, error):
                    self.create(create_launcher=True, launcher_scene_relative_path=target)
        marker = "snapshot/scene # POWERSHELL.rbxlx"
        (self.source / marker).write_bytes(b'<roblox version="4"/>')
        with self.assertRaisesRegex(archive.ArchiveError, "bootstrap marker"):
            self.create(create_launcher=True, launcher_scene_relative_path=marker)

    def test_legacy_native_launcher_metadata_remains_verifiable(self):
        (self.source / "native.rbxl").write_bytes(b"<roblox!fixture-native-header")
        self.create(native_scene_relative_path="native.rbxl", create_launcher=True)
        with zipfile.ZipFile(self.zip) as handle:
            metadata = json.loads(handle.read(archive.METADATA))
            checks = json.loads(handle.read(archive.MANIFEST))
        metadata.pop("launcherSceneRelativePath")
        metadata.pop("launcherSceneExplicit")
        payload = archive.json_bytes(metadata)
        for row in checks["files"]:
            if row["path"] == archive.METADATA:
                row.update(bytes=len(payload), sha256=archive.sha_bytes(payload))
        self.rewrite({archive.METADATA: payload, archive.MANIFEST: archive.json_bytes(checks)})
        result = archive.package_archive(self.source, verify_existing=self.zip)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["launcherSceneRelativePath"], "native.rbxl")

    def test_xml_launcher_cli_contract(self):
        result = subprocess.run([sys.executable, "-B", str(Path(SPEC.origin)),
                                 "--source", str(self.source), "--output", str(self.zip),
                                 "--create-launcher", "--launcher-scene-relative-path", "snapshot/scene.rbxlx"],
                                capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["launcherSceneRelativePath"], "snapshot/scene.rbxlx")

    @unittest.skipUnless(os.name == "nt", "CMD/PowerShell launcher checks require Windows")
    def test_xml_checkonly_integrity_and_discovery_never_execute_the_discovered_file(self):
        target = "snapshot/a 'quote' $(Write-Output INJECTED) & `tick.rbxlx"
        (self.source / target).write_bytes(b'<roblox version="4"/>')
        self.create(create_launcher=True, launcher_scene_relative_path=target)
        extracted = self.root / "extracted"
        with zipfile.ZipFile(self.zip) as handle:
            handle.extractall(extracted)
            text = handle.read(archive.LAUNCHER).decode("utf-8")
        self.assertIn("@('-task','EditFile','-localPlaceFile'", text)
        self.assertNotIn("PlayFile", text)
        # This is deliberately not an executable. Discovery must not launch it.
        studio = self.root / "local" / "Roblox" / "Versions" / "fixture" / "RobloxStudioBeta.exe"
        studio.parent.mkdir(parents=True)
        studio.write_bytes(b"not an executable")
        replaced = {"localappdata", "programfiles", "programfiles(x86)", "studio_exe"}
        env = {key: value for key, value in os.environ.items() if key.casefold() not in replaced}
        env.update(LOCALAPPDATA=str(self.root / "local"), ProgramFiles=str(self.root / "programs"),
                   **{"ProgramFiles(x86)": str(self.root / "programs-x86")})
        env["STUDIO_EXE"] = str(studio)
        command = ["cmd.exe", "/d", "/c", str(extracted / archive.LAUNCHER), "-CheckOnly"]
        run = subprocess.run(command, env=env, capture_output=True, timeout=30)
        output = (run.stdout + run.stderr).decode("utf-8", errors="replace")
        self.assertEqual(run.returncode, 0, output)
        self.assertIn("CheckOnly: no Studio process started", output)
        self.assertIn("$(Write-Output INJECTED)", output)
        self.assertIn(str(studio), output)
        # PowerShell initializes ProgramFiles from its process architecture on
        # startup. Set those roots in that same process to isolate discovery
        # from any real Studio installations on the test machine.
        discovery_env = dict(env, ARCHIVE_ROOT=str(extracted) + os.sep,
                             ARCHIVE_LAUNCHER=str(extracted / archive.LAUNCHER),
                             ARCHIVE_CHECK_ONLY="1", ARCHIVE_TEST_PROGRAMFILES=str(self.root / "programs"),
                             ARCHIVE_TEST_PROGRAMFILES86=str(self.root / "programs-x86"))
        discovery_env.pop("STUDIO_EXE")
        discovery = ("$env:ProgramFiles=$env:ARCHIVE_TEST_PROGRAMFILES;"
                     "${env:ProgramFiles(x86)}=$env:ARCHIVE_TEST_PROGRAMFILES86;"
                     "$p=[IO.File]::ReadAllText($env:ARCHIVE_LAUNCHER);$m='# POWERSHELL';"
                     "& ([ScriptBlock]::Create($p.Substring($p.LastIndexOf($m)+$m.Length)))")
        run = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-Command", discovery],
                             env=discovery_env, capture_output=True, timeout=30)
        output = (run.stdout + run.stderr).decode("utf-8", errors="replace")
        self.assertEqual(run.returncode, 0, output)
        self.assertIn("CheckOnly: no Studio process started", output)
        self.assertIn(str(studio), output)
        (extracted / target).write_bytes(b"tampered")
        run = subprocess.run(command, env=env, capture_output=True, timeout=30)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(b"checksum failed", run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
