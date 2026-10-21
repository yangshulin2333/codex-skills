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


if __name__ == "__main__":
    unittest.main(verbosity=2)
