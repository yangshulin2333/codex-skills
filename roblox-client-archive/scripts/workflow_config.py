#!/usr/bin/env python3
"""Read-only workflow configuration checks. Standard library; never runs tools."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote

WORKFLOW_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = WORKFLOW_ROOT / "templates"
MODE_OPTIONS = {
    "raw_archive": {"sourceRecovery": False, "staticPreview": False, "playPreview": False},
    "recover_source": {"sourceRecovery": True, "staticPreview": False, "playPreview": False},
    "preview": {"staticPreview": True},
}
INPUT_ROLES = (
    "exporterOriginal", "exporterReviewed", "fullApiDump", "captureEntrypoint",
    "downloadEntrypoint", "verificationEntrypoint",
)
MACHINE_PATH = re.compile(r"(?i)(?:file:///(?:[a-z]:/|/)|(?<![\w])(?:[a-z]:[\\/]|\\\\[^\s\\]+\\))")
ENV_TOKEN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|%([A-Za-z_][A-Za-z0-9_]*)%")
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
WINDOWS_RESERVED = re.compile(r"(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def within(path: Path, root: Path):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def digest(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def merge_known(base, override, prefix=""):
    if not isinstance(override, dict):
        raise ValueError(f"{prefix or 'config'} must be a JSON object")
    result = copy.deepcopy(base)
    for key, value in override.items():
        qualified = f"{prefix}.{key}" if prefix else key
        if key not in base:
            raise ValueError(f"Unknown field: {qualified}")
        if isinstance(base[key], dict):
            result[key] = merge_known(base[key], value, qualified)
        else:
            result[key] = value
    return result


def valid_id(value):
    return (
        isinstance(value, str) and bool(re.fullmatch(r"[\w-]+", value))
        and not WINDOWS_RESERVED.fullmatch(value)
    )


def safe_relative(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Relative paths must be nonempty portable forward-slash paths")
    if any(not component or component.endswith((" ", ".")) or WINDOWS_RESERVED.fullmatch(component.split(".")[0]) for component in value.split("/")):
        raise ValueError(f"Invalid portable path component: {value}")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive or any(p in (".", "..") for p in value.split("/")):
        raise ValueError(f"Unsafe relative path: {value}")
    if any(any(c in component for c in ':*?"<>|') for component in value.split('/')):
        raise ValueError(f"Invalid portable path component: {value}")
    return path


def expand_environment(value):
    def expand(match):
        name = match[1] or match[2]
        if name not in os.environ:
            raise ValueError(f"Environment variable is not set: {name}")
        return os.environ[name]
    return ENV_TOKEN.sub(expand, value)


def bind_path(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("Environment path must be a nonempty string or null")
    value = expand_environment(value)
    path = Path(value).expanduser()
    if os.name != "nt" and PureWindowsPath(value).is_absolute():
        raise ValueError("Windows absolute path must be remapped on this host")
    return (path if path.is_absolute() else WORKFLOW_ROOT / path).resolve()


def check_structure(config, template=False):
    errors = []
    if type(config.get("schemaVersion")) is not int or config["schemaVersion"] != 1:
        errors.append("schemaVersion must be integer 1")
    env = config["environment"]
    run = config["run"]
    if env["pathBase"] != "workflowRoot":
        errors.append("environment.pathBase must be workflowRoot")
    for key, value in env["paths"].items():
        if value is not None and (not isinstance(value, str) or not value):
            errors.append(f"environment.paths.{key} must be string or null")
        if template and value is not None:
            errors.append(f"Shared template cannot bind a machine role: {key}")
    discovery = env["discovery"]
    if type(discovery["useCurrentUserEnvironment"]) is not bool or not isinstance(discovery["additionalInstallRoots"], list):
        errors.append("Invalid environment.discovery types")
    elif any(not isinstance(v, str) or not v for v in discovery["additionalInstallRoots"]):
        errors.append("additionalInstallRoots entries must be nonempty strings")
    if template and discovery["additionalInstallRoots"]:
        errors.append("Shared template cannot bind install roots")
    if run["mode"] not in MODE_OPTIONS:
        errors.append("Unknown run.mode")
    else:
        for field, required in MODE_OPTIONS[run["mode"]].items():
            if run["optional"][field] is not required:
                errors.append(f"run.mode={run['mode']} requires optional.{field}={required}")
    for group in ("export", "optional"):
        for field, value in run[group].items():
            if field == "excludeTrees":
                if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                    errors.append("export.excludeTrees must be a string array")
            elif type(value) is not bool:
                errors.append(f"run.{group}.{field} must be boolean")
    if not run["export"]["preserveBytecode"] or not run["export"]["preserveReadableSource"]:
        errors.append("Original bytecode/readable Source preservation must remain enabled")
    if run["export"]["remoteDecompile"] or run["export"]["remoteLinkedSourceFallback"]:
        errors.append("Remote decompile/LinkedSource fallback is disabled in this workflow")
    if run["mode"] == "raw_archive" and run["export"]["decompile"]:
        errors.append("raw_archive cannot enable decompile")
    if run["mode"] == "recover_source" and not run["export"]["decompile"]:
        errors.append("recover_source requires export.decompile=true")
    if type(run["terrain"]["captureRaw"]) is not bool or type(run["terrain"]["restoreInStudio"]) is not bool:
        errors.append("terrain switches must be boolean")
    if run["terrain"]["restoreInStudio"] and not run["optional"]["nativeConversion"]:
        errors.append("Terrain Studio restore requires explicit nativeConversion")
    for field in ("workers", "requestsPerSecond", "timeoutSeconds", "maxAttempts"):
        value = run["download"][field]
        if type(value) not in (int, float) or value <= 0:
            errors.append(f"download.{field} must be positive")
    for field in ("workers", "maxAttempts"):
        if type(run["download"][field]) is not int:
            errors.append(f"download.{field} must be integer")
    max_bytes = run["download"]["maxAssetBytes"]
    if max_bytes is not None and (type(max_bytes) is not int or max_bytes <= 0):
        errors.append("download.maxAssetBytes must be positive integer or null")
    if run["download"]["useAccountCredentials"] is not False:
        errors.append("Credential-free resource acquisition is required")
    for key, value in run["inputs"].items():
        if value is not None and not valid_id(value):
            errors.append(f"run.inputs.{key} must be a safe artifactId or null")
    if template:
        if run["mode"] != "raw_archive" or any(run["optional"].values()) or run["export"]["decompile"]:
            errors.append("Shared template must default to raw archive only")
        for group in ("identity", "versions", "inputs"):
            if any(v is not None for v in run[group].values()):
                errors.append(f"Shared template cannot bind historical/current {group}")
        if run["derivedId"] is not None or run["inputArchiveArtifactId"] is not None:
            errors.append("Shared template cannot bind a run/input identity")
    return errors


def load_index(path, errors):
    index = read_json(path)
    if not isinstance(index, dict) or set(index) != {"schemaVersion", "artifacts"} or type(index["schemaVersion"]) is not int or index["schemaVersion"] != 1:
        raise ValueError("artifact index must contain only schemaVersion=1 and artifacts")
    records = index.get("artifacts")
    if not isinstance(records, list):
        raise ValueError("artifact index must have artifacts array")
    artifacts = {}
    for item in records:
        if not isinstance(item, dict) or not {"artifactId", "role", "rootRole", "relativePath"} <= set(item) or set(item) - {"artifactId", "role", "rootRole", "relativePath", "sha256", "bytes"}:
            errors.append("Artifact record has missing/unknown fields")
            continue
        aid = item.get("artifactId")
        if not valid_id(aid) or aid in artifacts:
            errors.append(f"Invalid/duplicate artifactId: {aid}")
            continue
        try:
            safe_relative(item.get("relativePath"))
        except ValueError as exc:
            errors.append(str(exc))
        if not isinstance(item.get("role"), str) or not item["role"]:
            errors.append(f"Missing resource role: {aid}")
        if item.get("rootRole") not in {
            "workflowRoot", "artifactRoot", "captureRoot", "xenoRoot", "xenoWorkspace",
        }:
            errors.append(f"Unknown rootRole for {aid}: {item.get('rootRole')}")
        expected_hash = item.get("sha256")
        if expected_hash is not None and (not isinstance(expected_hash, str) or not SHA256.fullmatch(expected_hash)):
            errors.append(f"Invalid SHA256: {aid}")
        if item.get("bytes") is not None and (type(item["bytes"]) is not int or item["bytes"] < 0):
            errors.append(f"Invalid bytes: {aid}")
        artifacts[aid] = item
    return artifacts


def resolve_record(item, roots):
    root = roots.get(item["rootRole"])
    if root is None:
        raise ValueError(f"Root role is unset: {item['rootRole']}")
    relative = safe_relative(item["relativePath"])
    path = root.joinpath(*relative.parts).resolve()
    if not within(path, root):
        raise ValueError(f"Artifact escapes root role: {item['artifactId']}")
    expected_hash = item.get("sha256")
    result = {
        "artifactId": item["artifactId"], "role": item["role"], "rootRole": item["rootRole"],
        "relativePath": item["relativePath"], "resolvedPath": str(path),
        "exists": path.exists(), "isFile": path.is_file(), "knownSha256": expected_hash,
        "sha256": None, "bytes": None, "hashMatches": None,
        "identityVerified": False,
    }
    if path.is_file():
        result["bytes"] = path.stat().st_size
        result["sha256"] = digest(path)
        if expected_hash is not None:
            result["hashMatches"] = result["sha256"].lower() == expected_hash.lower()
            result["identityVerified"] = result["hashMatches"]
    if item.get("bytes") is not None and result["bytes"] != item["bytes"]:
        result["sizeMatches"] = False
        result["identityVerified"] = False
    return result


def check_document_links(errors):
    external = []
    checked = 0
    pages = list(WORKFLOW_ROOT.glob("*.md")) + list((WORKFLOW_ROOT / "references").rglob("*.md"))
    for page in sorted(pages):
        text = page.read_text(encoding="utf-8-sig")
        fence = None
        for line_number, line in enumerate(text.splitlines(), 1):
            match = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
            if not match:
                continue
            delimiter = match[1]
            if fence is None:
                fence = (delimiter[0], len(delimiter), line_number)
            elif delimiter[0] == fence[0] and len(delimiter) >= fence[1] and not match[2].strip():
                fence = None
        if fence is not None:
            errors.append(f"Unclosed Markdown fence: {page.name}:{fence[2]}")
        if MACHINE_PATH.search(text):
            errors.append(f"Machine absolute path remains in shared document: {page.name}")
        targets = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", text)
        targets += re.findall(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", text)
        for target in targets:
            target = unquote(target.strip("<>"))
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            path_text, _, anchor = target.partition("#")
            if not path_text:
                destination = page
            else:
                destination = page.parent / path_text
                if destination.suffix == "":
                    destination = destination.with_suffix(".md")
                destination = destination.resolve()
            if not within(destination, WORKFLOW_ROOT):
                external.append({"page": str(page.relative_to(WORKFLOW_ROOT)), "target": target, "kind": "outside-skill"})
                errors.append(f"Shared document link escapes skill directory: {page.name} -> {target}")
                continue
            checked += 1
            if not destination.exists():
                errors.append(f"Broken internal link: {page.name} -> {target}")
            elif anchor and destination.suffix == ".md":
                contents = destination.read_text(encoding="utf-8-sig")
                anchors = set(re.findall(r'<a id="([^"]+)"', contents))
                headings = set(re.findall(r"^#+\s+(.+)$", contents, re.M))
                slugs = {re.sub(r"[^\w\s-]", "", h.lower()).strip().replace(" ", "-") for h in headings}
                if anchor not in anchors and anchor not in headings and anchor not in slugs:
                    errors.append(f"Broken internal anchor: {page.name} -> {target}")
    return checked, external


def check_asset_library_template(errors):
    path = TEMPLATE_ROOT / "asset-library.config.example.json"
    if not path.is_file():
        return None
    template = read_json(path)
    expected_keys = {"schemaVersion", "mode", "environment", "input", "policy", "outputs", "rights"}
    if not isinstance(template, dict) or set(template) != expected_keys:
        errors.append("Asset library template has missing/unknown top-level fields")
        return None
    if template["schemaVersion"] != 1 or template["mode"] != "organize_assets":
        errors.append("Asset library template must have schemaVersion=1 and mode=organize_assets")
    environment = template["environment"]
    if set(environment) != {"pathBase", "paths"} or environment["pathBase"] != "localConfigDirectory":
        errors.append("Asset library local paths must use localConfigDirectory")
    if set(environment["paths"]) != {"archive", "output", "luneExecutable"} or any(v is not None for v in environment["paths"].values()):
        errors.append("Asset library shared template must leave machine paths null")
    expected_inputs = {"archiveArtifactId", "expectedArchiveSha256", "sceneRelativePath", "assetManifestRelativePath", "scriptsIndexRelativePath"}
    if set(template["input"]) != expected_inputs or any(v is not None for v in template["input"].values()):
        errors.append("Asset library template must leave current input identities/paths null")
    expected_policy = {
        "rawReadOnly": True, "convertToLuau": False, "executeGameScripts": False,
        "launchStudio": False, "play": False, "deduplicateBySha256": True,
        "modelExportMode": "maximal_non_overlapping", "indexAllNestedModels": True,
        "parseAnimationContainers": True, "preserveUsageRoles": True, "preserveMissingDependencies": True,
    }
    if template["policy"] != expected_policy:
        errors.append("Asset library template violates read-only/raw-preservation/classification defaults")
    outputs = template["outputs"]
    if set(outputs) != {"pathsRelativeToLibraryRoot", "provenanceRelativeDir", "validationRelativeDir"} or outputs["pathsRelativeToLibraryRoot"] is not True:
        errors.append("Asset library outputs must use relative portable paths")
    for key in ("provenanceRelativeDir", "validationRelativeDir"):
        try:
            safe_relative(outputs[key])
        except (ValueError, KeyError) as exc:
            errors.append(f"Asset library {key}: {exc}")
    if template["rights"] != {"assetLicenseStatus": "not-established", "preserveToolLicenseRecords": True}:
        errors.append("Asset library template cannot assume a game asset license")
    return {"mode": template["mode"], "machinePathDefaults": "null", "sourceConversion": False, "modelExportMode": expected_policy["modelExportMode"]}


def check_template():
    errors = []
    template = read_json(TEMPLATE_ROOT / "config.example.json")
    # Roundtrip against the declared template catches wrong object shapes.
    template = merge_known(template, template)
    errors.extend(check_structure(template, template=True))
    artifacts = load_index(TEMPLATE_ROOT / "artifact-index.example.json", errors)
    asset_library_template = check_asset_library_template(errors)
    checked, external = check_document_links(errors)
    return {
        "command": "check-template", "scope": "read-only static workflow checks; no capture/tool execution",
        "status": "failed" if errors else "passed", "defaultMode": template["run"]["mode"],
        "exampleArtifactCount": len(artifacts), "internalLinksChecked": checked,
        "assetLibraryTemplate": asset_library_template,
        "externalDocumentDependencies": external, "errors": errors,
    }


def load_local(args):
    template = read_json(TEMPLATE_ROOT / "config.example.json")
    local = Path(args.local_config).resolve()
    if within(local, WORKFLOW_ROOT):
        raise ValueError("Real local config must be outside shared workflow directory")
    config = merge_known(template, read_json(local))
    if args.run_config:
        run_path = Path(args.run_config).resolve()
        if within(run_path, WORKFLOW_ROOT):
            raise ValueError("Run local config must be outside shared workflow directory")
        config = merge_known(config, read_json(run_path))
    roots = {key: bind_path(value) for key, value in config["environment"]["paths"].items()}
    roots["workflowRoot"] = WORKFLOW_ROOT
    return config, roots


def validate(args):
    config, roots = load_local(args)
    errors = check_structure(config)
    run = config["run"]
    identity = run["identity"]
    for key in ("captureId", "gameName", "sceneLabel"):
        if not isinstance(identity[key], str) or not identity[key]:
            errors.append(f"run.identity.{key} is unset")
    if not valid_id(identity["captureId"]):
        errors.append("captureId must be a safe unique directory segment")
    for key in ("expectedPlaceId", "expectedUniverseId"):
        if type(identity[key]) is not int or identity[key] <= 0:
            errors.append(f"{key} must be the verified positive current ID")
    required_roots = ["artifactRoot"]
    if run["mode"] == "raw_archive":
        required_roots += ["xenoRoot", "xenoWorkspace", "playerExecutable"]
        for key, version in run["versions"].items():
            if not isinstance(version, str) or not version:
                errors.append(f"run.versions.{key} is unset; verify current capture provenance")
    else:
        if not valid_id(run["derivedId"]):
            errors.append("A separate safe derivedId is required for derived outputs")
        if not valid_id(run["inputArchiveArtifactId"]):
            errors.append("A verified inputArchiveArtifactId is required")
    if run["optional"]["nativeConversion"] or run["optional"]["staticPreview"]:
        required_roots.append("studioExecutable")
    for key in required_roots:
        path = roots.get(key)
        if path is None:
            errors.append(f"Required environment role is unset: {key}")
        elif key.endswith("Executable") and not path.is_file():
            errors.append(f"Executable role is not an existing file: {key}")
        elif key != "artifactRoot" and not key.endswith("Executable") and not path.is_dir():
            errors.append(f"Directory role is not an existing directory: {key}")
    artifact_root = roots.get("artifactRoot")
    if artifact_root and (within(artifact_root, WORKFLOW_ROOT) or within(WORKFLOW_ROOT, artifact_root)):
        errors.append("artifactRoot must be separate from the shared skill directory")
    outputs = {}
    if artifact_root and valid_id(identity["captureId"]):
        for field, relative in run["paths"].items():
            if field == "derivedRelativeDir" and not valid_id(run["derivedId"]):
                continue
            try:
                relative = relative.format(captureId=identity["captureId"], derivedId=run["derivedId"])
                path = artifact_root.joinpath(*safe_relative(relative).parts).resolve()
                if not within(path, artifact_root):
                    raise ValueError(f"Output escapes artifactRoot: {field}")
                outputs[field] = str(path)
                if field == "captureRelativeDir":
                    roots["captureRoot"] = path
            except (ValueError, KeyError, AttributeError) as exc:
                errors.append(f"Invalid {field}: {exc}")
        paths = list(outputs.values())
        if len(set(paths)) != len(paths):
            errors.append("capture/package/derived output paths must be distinct")
        for i, path in enumerate(paths):
            for other in paths[i + 1:]:
                if within(Path(path), Path(other)) or within(Path(other), Path(path)):
                    errors.append("capture/package/derived output paths cannot contain one another")
    input_results = []
    capture_root = roots.get("captureRoot")
    if capture_root:
        try:
            index_path = capture_root.joinpath(*safe_relative(run["artifactIndexRelativePath"]).parts).resolve()
            if not within(index_path, capture_root):
                raise ValueError("artifact index escapes captureRoot")
            if not index_path.is_file():
                errors.append("This run needs an existing reviewed artifact-index.json at captureRoot")
            else:
                artifacts = load_index(index_path, errors)
                required_inputs = INPUT_ROLES if run["mode"] == "raw_archive" else ()
                if run["mode"] == "recover_source":
                    required_inputs += ("sourceRecoveryEntrypoint",)
                bound_ids = [(key, run["inputs"][key]) for key in required_inputs]
                if run["mode"] != "raw_archive":
                    bound_ids.append(("inputArchiveArtifactId", run["inputArchiveArtifactId"]))
                for role, aid in bound_ids:
                    if aid is None or aid not in artifacts:
                        errors.append(f"Required input artifact is unset/unresolved: {role}")
                        continue
                    result = resolve_record(artifacts[aid], roots)
                    input_results.append(result)
                    if not result["isFile"] or not result["identityVerified"] or result.get("sizeMatches") is False:
                        errors.append(f"Required input must be an existing hash-verified file: {role}")
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            errors.append(f"Artifact index validation: {exc}")
    return {
        "command": "validate", "scope": "read-only parameter/path/input checks; no attach/capture/download",
        "status": "failed" if errors else "passed", "mode": run["mode"],
        "identity": identity, "resolvedRolePaths": {k: str(v) if v else None for k, v in roots.items()},
        "resolvedOutputPaths": outputs, "inputs": input_results, "errors": errors,
    }


def resolve_artifact(args):
    config, roots = load_local(args)
    errors = []
    capture_id = config["run"]["identity"]["captureId"]
    artifact_root = roots.get("artifactRoot")
    if artifact_root and valid_id(capture_id):
        relative = config["run"]["paths"]["captureRelativeDir"].format(captureId=capture_id)
        capture_root = artifact_root.joinpath(*safe_relative(relative).parts).resolve()
        if not within(capture_root, artifact_root):
            raise ValueError("captureRoot escapes artifactRoot")
        roots["captureRoot"] = capture_root
    artifacts = load_index(Path(args.index).resolve(), errors)
    if args.artifact_id not in artifacts:
        raise ValueError(f"Unknown artifactId: {args.artifact_id}")
    result = resolve_record(artifacts[args.artifact_id], roots)
    if not result["exists"]:
        errors.append("Artifact path is absent; no successful resolution is claimed")
    if result["hashMatches"] is False or result.get("sizeMatches") is False:
        errors.append("Artifact content does not match recorded identity")
    result.update(command="resolve-artifact", status="failed" if errors else "passed", errors=errors)
    if result["knownSha256"] is None:
        result["identityNote"] = "No hash recorded; located file identity is not verified"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-template")
    for name in ("validate", "resolve-artifact"):
        command = sub.add_parser(name)
        command.add_argument("--local-config", required=True)
        command.add_argument("--run-config")
        if name == "resolve-artifact":
            command.add_argument("--artifact-id", required=True)
            command.add_argument("--index", required=True, help="Explicit local artifact index; no bundled personal history is read")
    args = parser.parse_args()
    try:
        result = check_template() if args.command == "check-template" else validate(args) if args.command == "validate" else resolve_artifact(args)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        result = {"command": args.command, "status": "failed", "scope": "read-only configuration check", "errors": [str(exc)]}
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
