"""Offline, temporary-fixture checks for configuration and provenance boundaries."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("archive_workflow_config", SKILL_ROOT / "scripts" / "workflow_config.py")
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


class ConfigChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.template = workflow.read_json(SKILL_ROOT / "templates" / "config.example.json")

    def write_json(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def fixture(self):
        config = copy.deepcopy(self.template)
        archive_root = self.root / "artifacts"
        tool_root = self.root / "tool"
        tool_root.mkdir()
        executable = tool_root / "fixture.exe"
        executable.write_bytes(b"fixture: not an executable")
        config["environment"]["paths"].update({
            "artifactRoot": str(archive_root), "xenoRoot": str(tool_root),
            "xenoWorkspace": str(tool_root), "playerExecutable": str(executable),
        })
        config["run"]["identity"].update({
            "gameName": "Synthetic fixture", "expectedPlaceId": 1, "expectedUniverseId": 2,
            "captureId": "fixture-001", "sceneLabel": "Test room",
        })
        for key in config["run"]["versions"]:
            config["run"]["versions"][key] = "fixture-1"
        capture = archive_root / "captures" / "fixture-001"
        capture.mkdir(parents=True)
        records = []
        for role in workflow.INPUT_ROLES:
            payload = capture / (role + ".txt")
            payload.write_text("fixture " + role, encoding="utf-8")
            config["run"]["inputs"][role] = role
            records.append({
                "artifactId": role, "role": role, "rootRole": "captureRoot",
                "relativePath": payload.name, "sha256": workflow.digest(payload), "bytes": payload.stat().st_size,
            })
        index = self.write_json("artifacts/captures/fixture-001/artifact-index.json", {"schemaVersion": 1, "artifacts": records})
        local = self.write_json("local.json", config)
        args = argparse.Namespace(local_config=str(local), run_config=None)
        return config, capture, index, args

    def test_shared_defaults_have_no_bound_machine_paths_or_derivation(self):
        self.assertEqual(workflow.check_structure(self.template, template=True), [])
        self.assertEqual(self.template["run"]["mode"], "raw_archive")
        self.assertFalse(any(self.template["run"]["optional"].values()))
        self.assertTrue(all(value is None for value in self.template["environment"]["paths"].values()))
        self.assertNotIn("vaultRoot", self.template["environment"]["paths"])

    def test_unknown_nested_fields_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown field"):
            workflow.merge_known(self.template, {"run": {"download": {"invented": True}}})

    def test_empty_local_config_is_not_a_valid_run(self):
        args = argparse.Namespace(local_config=str(self.write_json("empty.json", {})), run_config=None)
        result = workflow.validate(args)
        self.assertEqual(result["status"], "failed")
        self.assertIn("captureId must be a safe unique directory segment", result["errors"])

    def test_fixture_resolves_all_current_inputs_without_running_them(self):
        _, _, _, args = self.fixture()
        result = workflow.validate(args)
        self.assertEqual(result["status"], "passed", result["errors"])
        self.assertEqual(len(result["inputs"]), len(workflow.INPUT_ROLES))
        self.assertTrue(all(item["identityVerified"] for item in result["inputs"]))

    def test_changed_input_fails_hash_check(self):
        _, capture, _, args = self.fixture()
        (capture / "exporterReviewed.txt").write_text("changed", encoding="utf-8")
        result = workflow.validate(args)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("hash-verified" in error for error in result["errors"]))

    def test_output_path_traversal_rejected(self):
        config, _, _, args = self.fixture()
        config["run"]["paths"]["packageRelativeDir"] = "../escape"
        Path(args.local_config).write_text(json.dumps(config), encoding="utf-8")
        result = workflow.validate(args)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("Invalid packageRelativeDir" in error for error in result["errors"]))

    def test_output_nesting_rejected(self):
        config, _, _, args = self.fixture()
        config["run"]["paths"]["packageRelativeDir"] = "captures/{captureId}/package"
        Path(args.local_config).write_text(json.dumps(config), encoding="utf-8")
        self.assertTrue(any("cannot contain" in error for error in workflow.validate(args)["errors"]))

    def test_portable_path_boundaries(self):
        for value in ("../file", "/file", "C:/file", "a\\b", "a//b", "a/", "CON.txt", "file.", "a/./b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                workflow.safe_relative(value)
        self.assertEqual(str(workflow.safe_relative("assets/file.bin")), "assets/file.bin")

    def test_artifact_index_rejects_unknown_fields_and_bad_hash(self):
        errors = []
        malformed = self.write_json("index-invalid.json", {"schemaVersion": 1, "artifacts": [{"artifactId": "one", "role": "data", "rootRole": "artifactRoot", "relativePath": "one.bin", "sha256": "incorrect"}]})
        workflow.load_index(malformed, errors)
        self.assertEqual(errors, ["Invalid SHA256: one"])
        malformed = self.write_json("index-unknown.json", {"schemaVersion": 1, "artifacts": [], "personalHistory": []})
        with self.assertRaises(ValueError):
            workflow.load_index(malformed, [])

    def test_explicit_index_resolution_has_no_personal_history_fallback(self):
        _, _, index, args = self.fixture()
        args.index = str(index)
        args.artifact_id = "exporterOriginal"
        # captureRoot is normally produced by validate; choose an explicitly mapped root for this standalone command.
        d = workflow.read_json(index)
        d["artifacts"][0].update(rootRole="artifactRoot", relativePath="captures/fixture-001/exporterOriginal.txt")
        index.write_text(json.dumps(d), encoding="utf-8")
        result = workflow.resolve_artifact(args)
        self.assertEqual(result["status"], "passed", result["errors"])
        self.assertTrue(result["identityVerified"])
        args.index = str(self.root / "no-index.json")
        with self.assertRaises(FileNotFoundError):
            workflow.resolve_artifact(args)

    def test_symlink_cannot_escape_artifact_root(self):
        allowed = self.root / "allowed"
        allowed.mkdir()
        outside = self.root / "outside.bin"
        outside.write_bytes(b"outside")
        link = allowed / "link.bin"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Host does not permit temporary symlinks")
        with self.assertRaisesRegex(ValueError, "escapes root"):
            workflow.resolve_record({"artifactId": "test", "role": "data", "rootRole": "artifactRoot", "relativePath": "link.bin"}, {"artifactRoot": allowed})

    def test_environment_expansion_requires_defined_value(self):
        key = "ROBLOX_ARCHIVE_UNIT_TEST_MISSING_VARIABLE_7621"
        if key in os.environ:
            self.skipTest("Fixture variable happens to be defined")
        with self.assertRaisesRegex(ValueError, "not set"):
            workflow.expand_environment("${" + key + "}/file")

    def test_asset_library_template_defaults(self):
        errors = []
        summary = workflow.check_asset_library_template(errors)
        self.assertEqual(errors, [])
        self.assertEqual(summary["sourceConversion"], False)


if __name__ == "__main__":
    unittest.main()
