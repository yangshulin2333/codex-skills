"""Copy and inspect an existing Roblox client archive without running its code."""
from pathlib import Path
import argparse
import math
from collections import Counter
import base64
import hashlib
import json
import re
import shutil
import time
import xml.etree.ElementTree as ET

ROOT = None
EXPECTED_PLACE_ID = None
EXPECTED_UNIVERSE_ID = None
WORKSPACE = None
SNAPSHOT = None
SCRIPTS = None
SCRIPT_CLASSES = {"Script", "LocalScript", "ModuleScript", "CoreScript", "AuroraScript"}
BYTECODE_RE = re.compile(r"(?m)^-- Bytecode \(Base64\):[^\S\r\n]*\r?\n-- ([^\r\n]*)\r?\n(?:\r?\n)?")
SOURCE_MARKERS = {
    "-- Remote decompilation is disabled; accessible bytecode follows above.": "source_not_readable_remote_decompile_disabled",
    "-- Decompiling is disabled": "decompile_disabled",
    "-- Your Executor does NOT have a Decompiler": "decompiler_unavailable",
    "-- [FilteringEnabled] Server Scripts are IMPOSSIBLE to save": "server_source_not_replicated",
    "-- Ignored": "ignored_by_export_options",
    "-- The Script is Empty": "empty_script",
    "-- Not found in already decompiled ScriptCache": "source_missing_from_decompile_cache",
    "-- Not found in LinkedSource ScriptCache": "source_missing_from_linked_source_cache",
}

def json_write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

def checked_copy(source, destination):
    if source.is_symlink() or not source.resolve().is_relative_to(WORKSPACE.resolve()):
        raise RuntimeError(f"Unexpected export source path: {source}")
    with source.open("rb") as handle:
        source_sha = hashlib.file_digest(handle, "sha256").hexdigest()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        with destination.open("rb") as handle:
            existing_sha = hashlib.file_digest(handle, "sha256").hexdigest()
        if existing_sha != source_sha:
            raise RuntimeError(f"Different existing archive file: {destination}")
    else:
        pending = destination.with_name(destination.name + ".copy.tmp")
        shutil.copy2(source, pending)
        with pending.open("rb") as handle:
            pending_sha = hashlib.file_digest(handle, "sha256").hexdigest()
        if pending_sha != source_sha:
            raise RuntimeError(f"Pending archive copy digest mismatch: {pending}")
        pending.replace(destination)
    with destination.open("rb") as handle:
        copied_sha = hashlib.file_digest(handle, "sha256").hexdigest()
    if copied_sha != source_sha:
        raise RuntimeError(f"Archive copy digest mismatch: {destination}")
    return {"name": source.name, "bytes": source.stat().st_size, "sha256": source_sha}

def clean_source(value):
    value = re.sub(r"\A-- Saved by UniversalSynSaveInstance[^\r\n]*\r?\n(?:\r?\n)?", "", value)
    value = re.sub(r"\A-- Original Source:[^\r\n]*\r?\n(?:\r?\n)?", "", value)
    return BYTECODE_RE.sub("", value).strip()

def classification(value, path):
    content = clean_source(value)
    for marker, result in SOURCE_MARKERS.items():
        if content == marker:
            return result, content
    if not content:
        return "empty_source_property", content
    if content.startswith("--[[ Failed to decompile. Reason:"):
        return "decompile_failure_placeholder", content
    if "Thank you for using UniversalSynSaveInstance" in content and "This file was generated with the following settings:" in content:
        return "generated_export_readme", content
    return "readable_source", content


def check_production_records(inventory, finish):
    """Validate actual producer evidence instead of trusting one success flag."""
    required = ("diagnostic.json", "diagnostic-probe.txt", "export_start.json", "inventory-complete.txt", "unknown_class_remaps.json")
    for name in required:
        if not (WORKSPACE / name).is_file():
            raise ValueError("Missing capture producer record: " + name)
    diagnostic = json.loads((WORKSPACE / "diagnostic.json").read_text(encoding="utf-8-sig"))
    start = json.loads((WORKSPACE / "export_start.json").read_text(encoding="utf-8-sig"))
    if diagnostic.get("placeId") != EXPECTED_PLACE_ID or diagnostic.get("universeId") != EXPECTED_UNIVERSE_ID or diagnostic.get("loaded") is not True:
        raise ValueError("Diagnostic identity/load mismatch")
    if not diagnostic.get("diagnosticToken") or (WORKSPACE / "diagnostic-probe.txt").read_text(encoding="utf-8") != diagnostic["diagnosticToken"]:
        raise ValueError("Diagnostic write/read evidence differs")
    if diagnostic.get("placeVersion") != inventory.get("placeVersion"):
        raise ValueError("Diagnostic/inventory PlaceVersion differs")
    if start.get("PlaceId") != EXPECTED_PLACE_ID or start.get("GameId") != EXPECTED_UNIVERSE_ID:
        raise ValueError("Export start identity mismatch")
    if start.get("RemoteDecompile") is not False or finish.get("FilePresent") is not True:
        raise ValueError("Export producer policy/completion record differs")
    if start.get("OutputPath") != finish.get("OutputPath") or start.get("OutputPath") != str(inventory.get("outputFolder")) + "/scene.rbxlx":
        raise ValueError("Inventory/start/finish output paths differ")
    begun, ended = start.get("StartedUnix"), finish.get("FinishedUnix")
    if not isinstance(begun, (int, float)) or not isinstance(ended, (int, float)) or not math.isfinite(begun) or not math.isfinite(ended) or ended < begun or finish.get("StartedUnix") != begun:
        raise ValueError("Export producer timestamps are missing/inconsistent")
    classes = inventory.get("classCounts", {})
    if not isinstance(classes, dict) or not all(type(v) is int and v >= 0 for v in classes.values()) or sum(classes.values()) != inventory.get("instanceCount"):
        raise ValueError("Inventory instanceCount/classCounts inconsistent")
    scripts = inventory.get("scripts", [])
    if inventory.get("scriptCount") != len(scripts) or sum(v for k, v in classes.items() if k in SCRIPT_CLASSES) != len(scripts):
        raise ValueError("Inventory scriptCount/classCounts/script list inconsistent")
    script_counts = Counter(s.get("class") for s in scripts)
    if any(script_counts[k] != classes.get(k, 0) for k in SCRIPT_CLASSES):
        raise ValueError("Inventory script class list inconsistent")
    assets = inventory.get("assets", [])
    if inventory.get("assetCount") != len(assets):
        raise ValueError("Inventory assetCount/list inconsistent")
    marker = re.fullmatch(r"(\d+) instances; (\d+) asset URIs", (WORKSPACE / "inventory-complete.txt").read_text(encoding="utf-8").strip())
    if marker is None or [int(x) for x in marker.groups()] != [inventory["instanceCount"], len(assets)]:
        raise ValueError("Inventory completion marker/counts inconsistent")
    excluded = start.get("ExcludedEngineTrees")
    if not isinstance(excluded, list) or set(excluded) != {"CoreGui", "CorePackages", "PlatformLibraries"}:
        raise ValueError("Unsupported exporter scope; review adapter before accepting")
    scoped = inventory.get("exportScopeClassCounts")
    if scoped is not None:
        ignored = inventory.get("excludedRootClassCounts", {})
        if set(inventory.get("exportScopeExcludedRoots", [])) != set(excluded) or any(type(v) is not int or v < 0 for v in list(scoped.values()) + list(ignored.values())) or Counter(scoped) + Counter(ignored) != Counter(classes):
            raise ValueError("Inventory explicit export scope counts inconsistent")
    return {"producerRecordsChecked": list(required), "excludedEngineTrees": excluded,
            "inventoryInternalCountsPassed": True, "scopedClassCountsAvailable": scoped is not None,
            "producerRecordSha256": {name: hashlib.sha256((WORKSPACE / name).read_bytes()).hexdigest() for name in required}}


def compare_objects(inventory, classes, producer):
    """Account for excluded roots/remaps; reject unexplained substantial losses."""
    expected = Counter(inventory.get("exportScopeClassCounts", inventory["classCounts"]))
    exclusions = Counter()
    if "exportScopeClassCounts" not in inventory:
        for item in inventory["scripts"]:
            if str(item.get("path", "")).split(".")[0] in producer["excludedEngineTrees"]:
                exclusions[item["class"]] += 1
        expected.subtract(exclusions)
    remap_path = WORKSPACE / "unknown_class_remaps.json"
    remaps = json.loads(remap_path.read_text(encoding="utf-8-sig")) if remap_path.is_file() else []
    if not isinstance(remaps, list):
        raise ValueError("Unknown-class remap report is not a list")
    for item in remaps:
        name = item.get("ClassName")
        if name and expected[name] > 0:
            expected[name] -= 1
            expected["Folder"] += 1
    critical = SCRIPT_CLASSES | {"Part", "MeshPart", "UnionOperation", "WedgePart", "CornerWedgePart", "TrussPart", "Terrain"}
    differences, major = [], []
    for name in sorted(set(expected) | set(classes)):
        before, after = max(0, expected[name]), classes.get(name, 0)
        if before == after:
            continue
        difference = {"class": name, "expectedScopeCount": before, "exportedCount": after, "delta": after - before}
        differences.append(difference)
        lost = before - after
        if lost > 0 and name in critical and (name in SCRIPT_CLASSES or after == 0 or lost >= max(5, math.ceil(before * 0.05))):
            major.append(difference)
    total_expected, total_exported = sum(max(0, v) for v in expected.values()), sum(classes.values())
    if total_expected > 0 and total_exported < total_expected * 0.1:
        major.append({"class": "ALL_EXPORTED_OBJECTS", "expectedScopeCount": total_expected, "exportedCount": total_exported,
                      "note": "More than 90 percent reduction lacks scope/remap accounting; manual evidence required"})
    return {"basis": "explicit-export-scope" if "exportScopeClassCounts" in inventory else "legacy-live-inventory-with-known-script-root-exclusions",
            "differences": differences, "recordedUnknownClassRemaps": len(remaps),
            "scriptRootExclusions": dict(exclusions), "unexplainedMajorLosses": major,
            "knownTransformations": ["excluded engine roots", "Player/StarterPlayer isolation wrappers", "optional nil instances", "generated exporter ReadMe", "recorded unknown-class Folder remaps"],
            "exactSetEqualityClaimed": False, "manualReviewOfRemainingDifferencesRequired": bool(differences),
            "passedNoUnexplainedMajorLoss": not major}

def main():
    global ROOT, WORKSPACE, EXPECTED_PLACE_ID, EXPECTED_UNIVERSE_ID, SNAPSHOT, SCRIPTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--place-id", type=int, required=True)
    parser.add_argument("--universe-id", type=int, required=True)
    args = parser.parse_args()
    WORKSPACE = args.capture.resolve()
    ROOT = args.output.resolve()
    if ROOT == WORKSPACE or ROOT.is_relative_to(WORKSPACE) or WORKSPACE.is_relative_to(ROOT):
        parser.error("Capture and derived output must be separate, non-nested directories")
    if ROOT.exists():
        parser.error("Derived output already exists; choose a new directory")
    EXPECTED_PLACE_ID, EXPECTED_UNIVERSE_ID = args.place_id, args.universe_id
    SNAPSHOT, SCRIPTS = ROOT / "snapshot", ROOT / "scripts"
    ROOT.mkdir(parents=True)
    begun = time.time()
    finish_path = WORKSPACE / "export_finish.json"
    if not finish_path.exists():
        raise RuntimeError("New export not complete: export_finish.json missing")
    finish = json.loads(finish_path.read_text(encoding="utf-8-sig"))
    if finish.get("PlaceId") != EXPECTED_PLACE_ID or finish.get("GameId") != EXPECTED_UNIVERSE_ID:
        raise RuntimeError("Export target identity mismatch")
    scene_input = WORKSPACE / "scene.rbxlx"
    if not scene_input.exists() or finish.get("OutputBytes") != scene_input.stat().st_size:
        raise RuntimeError("Export scene byte count does not match completion record")
    if not finish.get("XmlRootPresent") or not finish.get("XmlEndPresent"):
        raise RuntimeError("Export completion record reports incomplete XML")
    inventory_input = WORKSPACE / "inventory.json"
    inventory = json.loads(inventory_input.read_text(encoding="utf-8-sig"))
    if inventory.get("placeId") != EXPECTED_PLACE_ID or inventory.get("universeId") != EXPECTED_UNIVERSE_ID:
        raise RuntimeError("Inventory target identity mismatch")
    producer_checks = check_production_records(inventory, finish)
    terrain_input = WORKSPACE / "terrain"
    if not (terrain_input / "probe-complete.txt").is_file():
        raise RuntimeError("Current terrain probe not complete")
    terrain_summary = json.loads((terrain_input / "probe-summary.json").read_text(encoding="utf-8-sig"))
    if terrain_summary.get("placeId") != EXPECTED_PLACE_ID or terrain_summary.get("universeId") != EXPECTED_UNIVERSE_ID:
        raise RuntimeError("Terrain probe target identity mismatch")
    checked_copy(inventory_input, ROOT / "inventory.json")
    for item in terrain_input.rglob("*"):
        if item.is_file():
            checked_copy(item, ROOT / "terrain" / item.relative_to(terrain_input))
    SNAPSHOT.mkdir(exist_ok=True)
    (SCRIPTS / "source").mkdir(parents=True, exist_ok=True)
    (SCRIPTS / "bytecode").mkdir(parents=True, exist_ok=True)
    copied = []
    for item in WORKSPACE.iterdir():
        if not item.is_file():
            continue
        destination = SNAPSHOT / item.name
        copied.append(checked_copy(item, destination))
    scene = SNAPSHOT / "scene.rbxlx"
    sha = hashlib.sha256()
    with scene.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            sha.update(chunk)
    count = 0
    top_level = []
    classes = Counter()
    script_classes = Counter()
    statuses = Counter()
    bytecode_total = 0
    bytecode_bytes = 0
    bytecode_versions = Counter()
    bytecode_errors = []
    empty_class_count = 0
    terrain = []
    stack = []
    element_stack = []
    index_path = SCRIPTS / "index.jsonl"
    script_records = []
    try:
        with index_path.open("w", encoding="utf-8") as index:
            for event, element in ET.iterparse(scene, events=("start", "end")):
                if event == "start":
                    if not element_stack and (element.tag != "roblox" or element.attrib.get("version") != "4"):
                        raise ValueError("Expected Roblox XML root with version 4")
                    element_stack.append(element)
                    if element.tag == "Item":
                        count += 1
                        class_name = element.attrib.get("class", "")
                        classes[class_name] += 1
                        if not class_name:
                            empty_class_count += 1
                        frame = {"class": class_name, "name": class_name, "referent": element.attrib.get("referent"), "parent": stack[-1] if stack else None, "source": None, "terrain": {}}
                        stack.append(frame)
                    continue
                if stack and len(element_stack) > 1 and element_stack[-2].tag == "Properties":
                    frame = stack[-1]
                    property_name = element.attrib.get("name")
                    if property_name == "Name":
                        frame["name"] = element.text or ""
                    elif property_name == "Source":
                        frame["source"] = element.text or ""
                    elif frame["class"] == "Terrain" and property_name in {"SmoothGrid", "PhysicsGrid", "MaterialColors", "AcquisitionMethod"}:
                        value = element.text or ""
                        details = {"xmlType": element.tag, "encodedCharacters": len(value)}
                        if element.tag == "BinaryString":
                            try:
                                decoded = base64.b64decode(re.sub(r"\s+", "", value), validate=True)
                                details.update(decodedBytes=len(decoded), sha256=hashlib.sha256(decoded).hexdigest())
                            except Exception as error:
                                details["decodeError"] = str(error)
                        else:
                            details["value"] = value[:300]
                        frame["terrain"][property_name] = details
                if element.tag == "Item":
                    frame = stack.pop()
                    path_parts = []
                    current = frame
                    while current:
                        path_parts.append(current["name"])
                        current = current["parent"]
                    full_path = ".".join(reversed(path_parts))
                    if frame["parent"] is None:
                        top_level.append({"name": frame["name"], "class": frame["class"], "referent": frame["referent"]})
                    if frame["class"] == "Terrain":
                        terrain.append({"path": full_path, "properties": frame["terrain"]})
                    if frame["class"] in SCRIPT_CLASSES:
                        seq = sum(script_classes.values()) + 1
                        script_classes[frame["class"]] += 1
                        content = frame["source"]
                        record = {"index": seq, "class": frame["class"], "fullPath": full_path, "referent": frame["referent"], "pathBasis": "Exported XML hierarchy after instance isolation/remapping", "sourcePropertyPresent": content is not None}
                        stem_name = re.sub(r"[^A-Za-z0-9_-]+", "_", frame["name"])[:55].strip("_") or "script"
                        identity = hashlib.sha256((full_path + "\0" + str(frame["referent"])).encode("utf-8")).hexdigest()[:12]
                        stem = f"{seq:05d}-{stem_name}-{identity}"
                        if content is None:
                            status = "source_property_missing"
                        else:
                            status, cleaned = classification(content, full_path)
                            record["sourcePropertyCharacters"] = len(content)
                            if status == "readable_source":
                                source_file = SCRIPTS / "source" / (stem + ".luau")
                                source_file.write_text(cleaned + "\n", encoding="utf-8")
                                record["sourceFile"] = source_file.relative_to(ROOT).as_posix()
                                record["sourceSha256"] = hashlib.sha256((cleaned + "\n").encode("utf-8")).hexdigest()
                            else:
                                record["placeholderPreview"] = cleaned[:400]
                            bytecode_match = BYTECODE_RE.search(content)
                            if bytecode_match:
                                try:
                                    raw = base64.b64decode(bytecode_match.group(1), validate=True)
                                    bytecode_file = SCRIPTS / "bytecode" / (stem + ".bin")
                                    bytecode_file.write_bytes(raw)
                                    record.update(bytecodeFile=bytecode_file.relative_to(ROOT).as_posix(), bytecodeBytes=len(raw), bytecodeSha256=hashlib.sha256(raw).hexdigest(), bytecodeFirstByte=raw[0] if raw else None,
                                                  bytecodeHeaderHex=raw[:16].hex(), bytecodeValidation="base64-and-hash-only-not-full-parser", bytecodeVersionCandidate=raw[0] if raw else None)
                                    bytecode_total += 1
                                    bytecode_bytes += len(raw)
                                    bytecode_versions[str(raw[0] if raw else None)] += 1
                                except Exception as error:
                                    record["bytecodeDecodeError"] = str(error)
                                    bytecode_errors.append({"path": full_path, "error": str(error)})
                        record["sourceStatus"] = status
                        statuses[status] += 1
                        index.write(json.dumps(record, ensure_ascii=False) + "\n")
                        script_records.append(record)
                    if len(element_stack) > 1:
                        element_stack[-2].remove(element)
                    element.clear()
                element_stack.pop()
        parsed = True
        parse_error = None
    except Exception as error:
        parsed = False
        parse_error = str(error)
    finish_path = SNAPSHOT / "export_finish.json"
    finish = json.loads(finish_path.read_text(encoding="utf-8")) if finish_path.exists() else None
    validation = {"scope": "Existing client-readable snapshot, not a complete server project", "execution": "No exported code executed", "copiedFiles": copied, "scene": {"path": str(scene), "bytes": scene.stat().st_size, "sha256": sha.hexdigest(), "xmlParsed": parsed, "parseError": parse_error, "items": count, "emptyClassNames": empty_class_count, "classCounts": dict(classes), "topLevelItems": top_level}, "scripts": {"count": sum(script_classes.values()), "classCounts": dict(script_classes), "sourceStatuses": dict(statuses), "readableSources": statuses["readable_source"], "bytecodeFiles": bytecode_total, "bytecodeBytes": bytecode_bytes, "bytecodeFirstByteCounts": dict(bytecode_versions), "bytecodeDecodeErrors": bytecode_errors, "index": str(index_path), "bytecodeLocationInScene": "Base64 comments inside script ProtectedString Source property", "placeholderRule": "Generated unavailable/ignored/decompile-disabled messages are not counted as readable source"}, "terrain": terrain, "exportCompletion": finish, "limitations": ["Streaming-enabled client snapshot contains only currently replicated/readable content", "Roblox engine trees explicitly excluded by exporter are listed in export_start.json", "Server-only scripts and storage are not recovered", "Unreadable client properties may be omitted or saved with exporter fallback defaults"], "validationSeconds": round(time.time() - begun, 3)}
    object_checks = compare_objects(inventory, classes, producer_checks)
    validation["producerCrossChecks"] = producer_checks
    validation["objectCrossChecks"] = object_checks
    validation["acceptancePassed"] = parsed and not bytecode_errors and object_checks["passedNoUnexplainedMajorLoss"]
    json_write(ROOT / "validation.json", validation)
    json_write(SCRIPTS / "index.json", {"pathBasis": "Exported XML hierarchy after instance isolation/remapping", "records": script_records})
    print(json.dumps({"xmlParsed": parsed, "acceptancePassed": validation["acceptancePassed"], "objectCrossChecks": object_checks,
                      "parseError": parse_error, "items": count, "scripts": validation["scripts"], "terrain": terrain, "validationSeconds": validation["validationSeconds"]}, ensure_ascii=False, indent=2))
    if not parsed:
        raise RuntimeError(parse_error)
    if not validation["acceptancePassed"]:
        raise RuntimeError("Archive acceptance failed: inspect bytecode errors and unexplained major object losses")

if __name__ == "__main__":
    main()
