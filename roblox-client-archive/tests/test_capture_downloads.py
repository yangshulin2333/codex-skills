"""Offline fixtures only: never attach to a game or make a network request."""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


DOWNLOAD = module("download_fixture", "scripts/downloads/download_assets.py")
VERIFY = module("verify_fixture", "scripts/downloads/verify_downloads.py")
PREPARE = module("prepare_fixture", "scripts/capture/prepare_capture.py")
TERRAIN = module("terrain_fixture", "scripts/capture/validate_terrain.py")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class CaptureDownloadsTests(unittest.TestCase):
    def test_canonical_and_dependency_boundaries(self):
        self.assertEqual(DOWNLOAD.canonical("rbxassetid://1234567890")[0], "id:1234567890")
        self.assertTrue(DOWNLOAD.canonical("rbxthumb://type=Avatar&id=123&w=420&h=420")[0].startswith("thumbnail:avatar:"))
        for uri in ("https://roblox.com.evil.invalid/a", "http://assetdelivery.roblox.com/v1/asset/?id=1", "file:///tmp/a"):
            self.assertIsNone(DOWNLOAD.canonical(uri))
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "dependencies.json"
            write_json(path, {"a": "rbxassetid://1234567890", "soundId": 27})
            refs, note = DOWNLOAD.dependencies(path)
            self.assertIsNone(note)
            self.assertIn("rbxassetid://1234567890", refs)
            self.assertIn("rbxassetid://27", refs)

    def test_builtin_download_hashes_missing_and_no_network(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            content = root / "content"
            content.mkdir()
            (content / "sample.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            inventory = {"placeId": 10, "universeId": 20, "assets": [
                {"uri": "rbxasset://sample.png", "references": []},
                {"uri": "rbxasset://missing.png", "references": []},
                {"uri": "rbxasset://../outside.png", "references": []},
                {"uri": "https://outside.invalid/a", "references": []}]}
            input_path = root / "inventory.json"
            write_json(input_path, inventory)
            args = SimpleNamespace(output=root / "assets", inventory=input_path, content_root=[content],
                                   workers=2, requests_per_second=4, attempts=2, timeout=1, max_asset_mib=1)
            with patch.object(DOWNLOAD.urllib.request, "build_opener", side_effect=AssertionError("network forbidden")), contextlib.redirect_stdout(io.StringIO()):
                DOWNLOAD.Downloader(args, inventory).run()
            manifest = args.output / "download-manifest.json"
            report = VERIFY.verify(args.output, manifest, 10, 20, input_path)
            self.assertTrue(report["integrityPassed"])
            self.assertFalse(report["allRequestsSucceeded"])
            self.assertEqual(len(report["verifiedFiles"]), 1)
            self.assertEqual(len(report["missingRequests"]), 2)
            self.assertEqual(len(report["rejectedReferences"]), 1)
            saved = args.output / report["verifiedFiles"][0]["file"]
            saved.write_bytes(b"tampered")
            self.assertFalse(VERIFY.verify(args.output, manifest, 10, 20, input_path)["integrityPassed"])
            self.assertFalse((args.output / ".partial").exists())
            with self.assertRaises(ValueError):
                VERIFY.verify(args.output, manifest, 11, 20, input_path)

    def test_download_manifest_path_traversal(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_json(root / "inventory.json", {"placeId": 10, "universeId": 20, "assets": [{"uri": "rbxassetid://1"}]})
            write_json(root / "inventory-binding.json", {"placeId": 10, "universeId": 20, "inventorySha256": sha((root / "inventory.json").read_bytes())})
            write_json(root / "manifest.json", {"summary": {"placeId": 10, "universeId": 20},
                        "assets": [{"key": "id:1", "status": "success", "file": "../secret", "bytes": 0, "sha256": "0" * 64}]})
            report = VERIFY.verify(root, root / "manifest.json", 10, 20, root / "inventory.json")
            self.assertFalse(report["integrityPassed"])
            self.assertIn("unsafe", report["errors"][0]["error"])

    def test_real_builtin_html_is_not_published_as_success(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            content = root / "content"
            content.mkdir()
            (content / "fake.png").write_bytes(b"<html><body>403 Forbidden</body></html>")
            inventory = {"placeId": 10, "universeId": 20, "assets": [{"uri": "rbxasset://fake.png"}]}
            input_path = root / "inventory.json"
            write_json(input_path, inventory)
            args = SimpleNamespace(output=root / "assets", inventory=input_path, content_root=[content],
                                   workers=1, requests_per_second=4, attempts=1, timeout=1, max_asset_mib=1)
            with patch.object(DOWNLOAD.urllib.request, "build_opener", side_effect=AssertionError("network forbidden")), contextlib.redirect_stdout(io.StringIO()):
                DOWNLOAD.Downloader(args, inventory).run()
            data = json.loads((args.output / "download-manifest.json").read_text())
            self.assertNotEqual(data["assets"][0]["status"], "success")
            self.assertFalse(list((args.output / "objects").rglob("*")) if (args.output / "objects").exists() else [])

    def test_manifest_closure_counts_binding_and_error_body(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            inventory_path = root / "inventory.json"
            inventory = {"placeId": 10, "universeId": 20, "assets": [{"uri": "rbxassetid://1"}]}
            write_json(inventory_path, inventory)
            binding = {"placeId": 10, "universeId": 20, "inventorySha256": sha(inventory_path.read_bytes())}
            write_json(root / "inventory-binding.json", binding)
            obj = root / "objects/good.png"
            obj.parent.mkdir()
            obj.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            record = {"key": "id:1", "status": "success", "file": "objects/good.png", "bytes": obj.stat().st_size,
                      "sha256": sha(obj.read_bytes()), "extension": ".png", "dependencies": []}
            summary = {"placeId": 10, "universeId": 20, "inventory_assets": 1, "unique_requests_with_dependencies": 1}
            def verify_case(changes=None, rejected=None):
                write_json(root / "manifest.json", {"summary": summary, "assets": [{**record, **(changes or {})}], "rejected": rejected or []})
                return VERIFY.verify(root, root / "manifest.json", 10, 20, inventory_path)
            self.assertTrue(verify_case()["allRequestsSucceeded"])
            self.assertFalse(verify_case({"dependencies": ["rbxassetid://2"]})["integrityPassed"])
            summary["unique_requests_with_dependencies"] = 999
            self.assertFalse(verify_case()["integrityPassed"])
            summary["unique_requests_with_dependencies"] = 1
            self.assertFalse(verify_case(rejected=[{"uri": "unsupported://lost", "reason": "unsupported"}])["allRequestsSucceeded"])
            obj.write_bytes(b"<html><body>403 Forbidden</body></html>")
            self.assertFalse(verify_case({"bytes": obj.stat().st_size, "sha256": sha(obj.read_bytes())})["integrityPassed"])
            write_json(root / "inventory-binding.json", {**binding, "inventorySha256": "0" * 64})
            with self.assertRaisesRegex(ValueError, "inventory SHA256"):
                verify_case()

    def prepare_fixture(self, root):
        workspace = root / "workspace"
        workspace.mkdir()
        source = '\n'.join([
            'game:HttpGet("https://raw.githubusercontent.com/luau/SomeHub/main/" .. filename .. ".luau", true)',
            'game:HttpGet("https://raw.githubusercontent.com/luau/SomeHub/main/" .. filename .. ".luau", true)',
            'local USSI_FOLDER = "ussi_cache/"',
            '\t\tldecompile = function()\n\t\t\treturn "-- Decompiling is disabled"\n\t\tend',
            '\t\tfor i, fetcher in APIDUMP_FETCHERS do\n\t\t\tlocal o, r = pcall(fetcher)',
            'local API_Dump_Decoded = API_Dump',
            'return game:HttpGet("https://assetdelivery.roproxy.com/v1/asset/?" .. asset)',
            'game:HttpGet(\n\t\t\t\t\t\t"https://raw.githubusercontent.com/daily3014/rbx-algorithms/refs/heads/main/src/Encoding/Base64.luau",\n\t\t\t\t\t\ttrue\n\t\t\t\t\t)',
            'game:HttpGet("https://raw.githubusercontent.com/RiskoZS/llz4/refs/heads/main/llz4.luau", true)',
            'unknownTag, class, propClass = class, "Folder", "Instance"',
            'local name = virtual and override.Properties.Name or instance.Name',
            'local GLOBAL_ENV = getgenv and getgenv() or _G or shared'])
        payloads = {"exporter": source.encode(), "apiDump": json.dumps({"Classes": [{"Members": [{"MemberType": "Property", "Default": 0}]}]}).encode()}
        payloads.update({n: ("-- fixture " + n).encode() for n in PREPARE.MODULES + PREPARE.LICENSES})
        inputs = {}
        for key, data in payloads.items():
            path = root / (key + ".input")
            path.write_bytes(data)
            inputs[key] = {"path": path.name, "sha256": sha(data)}
        return {"placeId": 10, "universeId": 20, "runId": "fixture-1", "xenoWorkspace": str(workspace),
                "toolsDirectory": "archive_tools_fixture", "captureDirectory": "client_archive_fixture",
                "clientFullVersion": "0.1.2.3", "inputs": inputs,
                "terrain": {"enabled": True, "captureName": "box-1", "min": [0, 0, 0],
                            "maxExclusive": [8, 8, 8], "chunkStuds": [8, 8, 8], "resolution": 4}}

    def test_prepare_pinned_inputs_no_execution_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            config = self.prepare_fixture(root)
            report = PREPARE.prepare(config, root, True)
            target = Path(config["xenoWorkspace"]) / config["toolsDirectory"]
            self.assertFalse(target.exists())
            self.assertEqual(report["mode"], "prepared-only-not-executed")
            PREPARE.prepare(config, root)
            self.assertIn('["placeId"]=10', (target / "inventory.luau").read_text(encoding="utf-8"))
            self.assertIn('["min"]={0,0,0}', (target / "terrain_capture.luau").read_text(encoding="utf-8"))
            self.assertFalse((Path(config["xenoWorkspace"]) / config["captureDirectory"]).exists())
            with self.assertRaises(ValueError):
                PREPARE.prepare(config, root)

    def test_prepare_rejects_changed_hash_and_unknown_source(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            config = self.prepare_fixture(root)
            config["inputs"]["exporter"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "SHA256"):
                PREPARE.prepare(config, root)
            self.assertFalse((Path(config["xenoWorkspace"]) / config["toolsDirectory"]).exists())
        with self.assertRaisesRegex(ValueError, "layout changed"):
            PREPARE.patch_exporter("-- new upstream layout", "tools")

    def test_xml_copy_and_bytecode_extraction_cli(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            capture = root / "capture"
            capture.mkdir()
            roblox = ET.Element("roblox", {"version": "4"})
            for index, source in enumerate(("print('readable')", "-- Bytecode (Base64):\n-- " + base64.b64encode(b"\x0d\x01fixture").decode() + "\n\n-- Remote decompilation is disabled; accessible bytecode follows above.")):
                item = ET.SubElement(roblox, "Item", {"class": "ModuleScript", "referent": str(index)})
                properties = ET.SubElement(item, "Properties")
                ET.SubElement(properties, "string", {"name": "Name"}).text = "Fixture" + str(index)
                ET.SubElement(properties, "ProtectedString", {"name": "Source"}).text = source
            scene = ET.tostring(roblox, encoding="utf-8")
            (capture / "scene.rbxlx").write_bytes(scene)
            producer = {"PlaceId": 10, "GameId": 20, "StartedUnix": 1, "OutputPath": "client_archive_fixture/scene.rbxlx", "RemoteDecompile": False,
                        "ExcludedEngineTrees": ["CoreGui", "CorePackages", "PlatformLibraries"]}
            write_json(capture / "export_start.json", producer)
            write_json(capture / "export_finish.json", {**producer, "FinishedUnix": 2, "FilePresent": True, "OutputBytes": len(scene), "XmlRootPresent": True, "XmlEndPresent": True})
            write_json(capture / "diagnostic.json", {"placeId": 10, "universeId": 20, "placeVersion": 9, "loaded": True, "diagnosticToken": "fixture"})
            (capture / "diagnostic-probe.txt").write_text("fixture")
            write_json(capture / "unknown_class_remaps.json", [])
            write_json(capture / "inventory.json", {"placeId": 10, "universeId": 20, "placeVersion": 9, "outputFolder": "client_archive_fixture",
                       "assets": [], "assetCount": 0, "instanceCount": 2, "classCounts": {"ModuleScript": 2},
                       "scriptCount": 2, "scripts": [{"path": "Workspace.Fixture0", "class": "ModuleScript"}, {"path": "Workspace.Fixture1", "class": "ModuleScript"}]})
            (capture / "inventory-complete.txt").write_text("2 instances; 0 asset URIs")
            write_json(capture / "terrain/probe-summary.json", {"placeId": 10, "universeId": 20})
            (capture / "terrain/probe-complete.txt").write_text("fixture")
            output = root / "derived"
            command = [sys.executable, str(ROOT / "scripts/capture/validate_and_extract.py"), "--capture", str(capture), "--output", str(output), "--place-id", "10", "--universe-id", "20"]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            records = json.loads((output / "scripts/index.json").read_text())["records"]
            self.assertEqual(records[0]["sourceStatus"], "readable_source")
            self.assertEqual(records[1]["sourceStatus"], "source_not_readable_remote_decompile_disabled")
            self.assertEqual(records[1]["bytecodeVersionCandidate"], 13)
            self.assertEqual(sha((output / "snapshot/scene.rbxlx").read_bytes()), sha(scene))
            self.assertEqual(sha((capture / "scene.rbxlx").read_bytes()), sha(scene))
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            write_json(capture / "terrain/probe-summary.json", {"placeId": 10, "universeId": 999})
            bad_identity = command.copy()
            bad_identity[bad_identity.index("--output") + 1] = str(root / "bad-identity")
            identity_result = subprocess.run(bad_identity, capture_output=True, text=True)
            self.assertNotEqual(identity_result.returncode, 0)
            self.assertIn("Terrain probe target identity mismatch", identity_result.stderr)
            write_json(capture / "terrain/probe-summary.json", {"placeId": 10, "universeId": 20})
            lost_scene = b'<roblox version="4"><Item class="Folder" referent="f"><Properties><string name="Name">OnlyFolder</string></Properties></Item></roblox>'
            (capture / "scene.rbxlx").write_bytes(lost_scene)
            write_json(capture / "export_finish.json", {**producer, "FinishedUnix": 2, "FilePresent": True, "OutputBytes": len(lost_scene), "XmlRootPresent": True, "XmlEndPresent": True})
            loss_command = command.copy()
            loss_root = root / "lost-objects"
            loss_command[loss_command.index("--output") + 1] = str(loss_root)
            lost = subprocess.run(loss_command, capture_output=True, text=True)
            self.assertNotEqual(lost.returncode, 0)
            loss_report = json.loads((loss_root / "validation.json").read_text())
            self.assertFalse(loss_report["acceptancePassed"])
            self.assertTrue(loss_report["objectCrossChecks"]["unexplainedMajorLosses"])

    def test_terrain_index_gap_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "chunks").mkdir()
            (root / "capture-complete.txt").write_text("fixture")
            summary = {"placeId": 10, "universeId": 20, "completeExplicitBox": True, "completeWholeWorld": False,
                       "gameObjectsModified": False, "bounds": {"min": [0, 0, 0], "maxExclusive": [8, 8, 8], "resolution": 4},
                       "chunkStuds": [8, 8, 8], "totals": {"plannedChunks": 1}, "materials": {"0": {"value": 0, "name": "Air"}}, "index": "chunk-index.jsonl"}
            write_json(root / "capture-start.json", summary)
            write_json(root / "capture-summary.json", summary)
            (root / "chunk-index.jsonl").write_text("")
            TERRAIN.CAPTURE, TERRAIN.PLACE, TERRAIN.UNIVERSE = root, 10, 20
            with self.assertRaisesRegex(ValueError, "every planned chunk"):
                TERRAIN.validate()

    def test_terrain_full_rle_and_default_box(self):
        for occupied in (True, False):
            with self.subTest(occupied=occupied), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                (root / "chunks").mkdir()
                (root / "capture-complete.txt").write_text("fixture")
                cells = 8 if occupied else 0
                entry = {"index": 1, "origin": [0, 0, 0], "sizeInCells": [2, 2, 2], "ok": True,
                         "voxels": 8, "empty": not occupied, "nonemptyCells": cells, "solidCells": cells,
                         "liquidCells": cells, "nondefaultCells": cells}
                totals = {"plannedChunks": 1, "completedChunks": 1, "failedChunks": 0,
                          "nonemptyChunks": 1 if occupied else 0, "emptyChunks": 0 if occupied else 1,
                          "scannedVoxels": 8, "nonemptyCells": cells, "solidCells": cells,
                          "liquidCells": cells, "nondefaultCells": cells}
                summary = {"placeId": 10, "universeId": 20, "completeExplicitBox": True, "completeWholeWorld": False,
                           "gameObjectsModified": False, "bounds": {"min": [0, 0, 0], "maxExclusive": [8, 8, 8], "resolution": 4},
                           "chunkStuds": [8, 8, 8], "totals": totals, "materials": {"0": {"value": 0, "name": "Air"}, "1": {"value": 1, "name": "FixtureSolid"}},
                           "index": "chunk-index.jsonl", "filledMin": [0, 0, 0] if occupied else None,
                           "filledMaxExclusive": [8, 8, 8] if occupied else None,
                           "CountCellsBefore": {"ok": False}, "CountCellsAfter": {"ok": False}}
                if occupied:
                    payload = {"schema": "codex-terrain-rle-v2", "origin": [0, 0, 0], "size": [2, 2, 2], "resolution": 4,
                               "order": "x-major,y-middle,z-fastest", "fields": ["runLength", "Enum.Material.Value", "SolidOccupancy", "LiquidOccupancy"],
                               "runs": [8, 1, 0.5, 0.25], "materials": {"1": {"value": 1, "name": "FixtureSolid"}},
                               "nonemptyCells": 8, "solidCells": 8, "liquidCells": 8, "nondefaultCells": 8,
                               "filledMin": [0, 0, 0], "filledMaxExclusive": [8, 8, 8], "dataMin": [0, 0, 0], "dataMaxExclusive": [8, 8, 8]}
                    write_json(root / "chunks/chunk-0001.json", payload)
                    entry.update(file="chunks/chunk-0001.json", bytes=(root / "chunks/chunk-0001.json").stat().st_size, runs=1)
                write_json(root / "capture-start.json", summary)
                write_json(root / "capture-summary.json", summary)
                (root / "chunk-index.jsonl").write_text(json.dumps(entry) + "\n")
                TERRAIN.CAPTURE, TERRAIN.PLACE, TERRAIN.UNIVERSE = root, 10, 20
                result = TERRAIN.validate()
                self.assertTrue(result["passed"])
                self.assertEqual(result["countedLiquid"], cells)

    def test_all_cli_help_is_offline(self):
        for script in ("capture/prepare_capture.py", "capture/validate_and_extract.py", "capture/validate_terrain.py", "downloads/download_assets.py", "downloads/verify_downloads.py"):
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / script), "--help"], capture_output=True)
            self.assertEqual(result.returncode, 0, script)


if __name__ == "__main__":
    unittest.main()
