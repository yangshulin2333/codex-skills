#!/usr/bin/env python3
"""Build an offline library from hash-verified successful archive downloads.

Only archived manifests, inventories and downloaded bytes are read. No network,
account credentials, cache scanning, or archived script execution is used.
An optional Lune executable inspects Roblox containers as offline data only.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unicodedata


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def relative(path, root):
    path, root = path.resolve(), root.resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path escaped its bound root: " + str(path))
    return path.relative_to(root).as_posix()


def magic_extension(path):
    with path.open("rb") as stream:
        head = stream.read(256)
    stripped = head.lstrip()
    if head.startswith(b"\x89PNG\r\n\x1a\n"): return ".png"
    if head.startswith(b"\xff\xd8\xff"): return ".jpg"
    if head.startswith(b"DDS "): return ".dds"
    if head.startswith(b"OggS"): return ".ogg"
    if head.startswith(b"ID3") or head[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}: return ".mp3"
    if head.startswith(b"version "): return ".mesh"
    if head.startswith(b"<roblox!"): return ".rbxm"
    if stripped.startswith((b"<roblox", b"<?xml")) and b"<roblox" in head: return ".rbxmx"
    if head.startswith(b"OTTO"): return ".otf"
    if head.startswith(b"\0\x01\0\0"): return ".ttf"
    if stripped.startswith((b"{", b"[")): return ".json"
    return None


def usage(reference):
    """Tags describe actual class/property references; name-only inferences stay candidates."""
    cls = str(reference.get("class", ""))
    prop = str(reference.get("property", ""))
    low = prop.lower()
    tags = set()
    basis = []
    if cls == "SurfaceAppearance" and low in {"colormap", "metalnessmap", "normalmap", "roughnessmap"}:
        tag = "pbr:" + {"colormap": "base-color", "metalnessmap": "metalness", "normalmap": "normal", "roughnessmap": "roughness"}[low]
        tags.add(tag)
        basis.append({"tag": tag, "basis": "SurfaceAppearance." + prop, "confidence": "explicit_property"})
    if low in {"image", "hoverimage", "pressedimage"} and cls in {"ImageLabel", "ImageButton"}:
        tags.add("ui:image")
        basis.append({"tag": "ui:image", "basis": cls + "." + prop, "confidence": "explicit_property"})
    if low in {"texture", "textureid"}:
        roles = {"ParticleEmitter": "particle:texture", "Beam": "beam:texture", "Trail": "trail:texture",
                 "Decal": "decal:texture", "Texture": "surface:tiled-texture", "MeshPart": "surface:mesh-texture",
                 "SpecialMesh": "surface:mesh-texture"}
        if cls in roles:
            tag = roles[cls]
            tags.add(tag)
            basis.append({"tag": tag, "basis": cls + "." + prop, "confidence": "explicit_property"})
    if low == "meshid":
        tags.add("model:mesh-reference")
        basis.append({"tag": "model:mesh-reference", "basis": cls + "." + prop, "confidence": "explicit_property"})
    if low == "animationid":
        tags.add("animation:reference")
        basis.append({"tag": "animation:reference", "basis": cls + "." + prop, "confidence": "explicit_property"})
    if low == "soundid":
        tags.add("audio:sound-reference")
        basis.append({"tag": "audio:sound-reference", "basis": cls + "." + prop, "confidence": "explicit_property"})
    if low == "staticbytecodeassetreference":
        tags.add("reference:static-bytecode")
        basis.append({"tag": "reference:static-bytecode", "basis": str(reference.get("kind", "static evidence")), "confidence": "explicit_static_reference_only"})
    if low in {"font", "fontface"}:
        tags.add("other:font-reference")
    path = str(reference.get("path", ""))
    if low == "soundid" and re.search(r"(?:^|[./\\])(?:music|bgm|backgroundmusic|musiccontroller)(?:[./\\]|$)", path, re.I):
        tag = "candidate:music-by-reference-path"
        tags.add(tag)
        basis.append({"tag": tag, "basis": path, "confidence": "name_candidate_not_audio_analysis"})
    return tags, basis


def safe_name(value):
    value = unicodedata.normalize("NFC", str(value))
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", "_", value).strip(" ._")
    value = value[:80].strip(" ._") or "content"
    if value.upper() in {"CON", "PRN", "AUX", "NUL", *["COM" + str(i) for i in range(1, 10)], *["LPT" + str(i) for i in range(1, 10)]}:
        value = "asset_" + value
    return value


def observed(command, evidence, label):
    stdout_path, stderr_path = evidence / (label + ".stdout.log"), evidence / (label + ".stderr.log")
    start = now()
    with stdout_path.open("xb") as out, stderr_path.open("xb") as err:
        result = subprocess.run(command, stdout=out, stderr=err, check=False)
    record = {"command": command, "startedUtc": start, "finishedUtc": now(), "exitStatus": result.returncode,
              "stdout": str(stdout_path), "stderr": str(stderr_path), "stdoutSha256": sha(stdout_path), "stderrSha256": sha(stderr_path)}
    return record


def build(args):
    archive, evidence = args.archive.resolve(), args.evidence_dir.resolve()
    output = args.output.resolve() if args.output else None
    if output is not None and (output == archive or output.is_relative_to(archive) or archive.is_relative_to(output)):
        raise ValueError("Library output must be separate from the immutable archive")
    if evidence == archive or evidence.is_relative_to(archive):
        raise ValueError("Evidence output must be outside the immutable archive")
    evidence.mkdir(parents=True, exist_ok=True)
    if not args.check_inputs_only:
        output.mkdir(parents=True, exist_ok=True)
        if (output / "download-index.json").exists():
            raise ValueError("download-index.json already exists; choose a new output or verify the existing library")
    canonical_path = archive / "download-validation.json"
    if not canonical_path.is_file():
        canonical_path = archive / "validation/download-validation.json"
    canonical_hash = sha(canonical_path)
    canonical = load(canonical_path)
    if not canonical.get("integrity_and_scope_passed") or canonical.get("validation_errors"):
        raise ValueError("Archive canonical verification did not pass")
    original_root = str(canonical.get("root", archive)).replace("\\", "/").rstrip("/")

    def recorded_path(value, controlled_metadata=False):
        normalized = str(value).replace("\\", "/")
        if normalized.lower().startswith(original_root.lower() + "/"):
            normalized = normalized[len(original_root) + 1:]
        elif re.match(r"^(?:[A-Za-z]:/|/)", normalized):
            path = Path(value).resolve()
            if path.is_relative_to(archive): return path
            raise ValueError("Recorded path has no current archive provenance: " + str(value))
        path = (archive / normalized).resolve()
        relative(path, archive)
        if not path.is_file() and controlled_metadata:
            relocated = (archive / "validation" / normalized).resolve()
            relative(relocated, archive)
            if relocated.is_file():
                path = relocated
        return path

    expected = {item["file"]: item for item in canonical["files"]}
    source_files, content, histories, effective, seen_paths, source_proofs = {}, {}, {}, {}, set(), []
    manifest_data = []
    for entry in canonical["manifest_reports"]:
        manifest_path = recorded_path(entry["path"], controlled_metadata=True)
        manifest_hash = sha(manifest_path)
        if manifest_hash != entry["sha256"]:
            raise ValueError("Manifest hash changed: " + entry["path"])
        manifest = load(manifest_path)
        summary = manifest["summary"]
        if (summary["placeId"] != canonical["placeId"] or summary["universeId"] != canonical["universeId"]):
            raise ValueError("Manifest game identity differs")
        inventory_path = recorded_path(summary["inventory_file"], controlled_metadata=True)
        inventory_hash = sha(inventory_path)
        if inventory_hash != summary["inventory_sha256"]:
            raise ValueError("Source inventory hash changed")
        inventory = load(inventory_path)
        manifest_rel, inventory_rel = relative(manifest_path, archive), relative(inventory_path, archive)
        source_proofs.append({"path": manifest_rel, "sha256": manifest_hash, "inventoryPath": inventory_rel, "inventorySha256": inventory_hash})
        for record in manifest["assets"]:
            key, status = record["key"], record["status"]
            refs = []
            for index in record.get("inventory_indices", []):
                if not isinstance(index, int) or not 0 <= index < len(inventory["assets"]):
                    raise ValueError("Invalid inventory reference index")
                for ref in inventory["assets"][index].get("references", []):
                    refs.append({**ref, "inventoryPath": inventory_rel, "inventorySha256": inventory_hash, "inventoryIndex": index,
                                 "referenceRelation": "direct_inventory_property"})
            proof = {"manifestPath": manifest_rel, "manifestSha256": manifest_hash, "inventoryPath": inventory_rel,
                     "inventorySha256": inventory_hash, "key": key, "status": status, "httpStatus": record.get("http_status"),
                     "inventoryIndices": record.get("inventory_indices", []), "parentKeys": record.get("parents", [])}
            history = {**proof, "id": record.get("id"), "uri": record.get("uri"), "sourceUris": record.get("source_uris", []),
                       "attempts": record.get("attempts"), "error": record.get("error"), "finishedUtc": record.get("finished_utc"),
                       "sha256": record.get("sha256"), "references": refs, "dependencies": record.get("dependencies", [])}
            histories.setdefault(key, []).append(history)
            previous = effective.get(key)
            if previous is None or previous["status"] != "success" or status == "success":
                effective[key] = history
            if status != "success": continue
            file_path = (manifest_path.parent / record["file"]).resolve()
            relative(file_path, manifest_path.parent)
            file_rel = relative(file_path, archive)
            expected_file = expected.get(file_rel)
            if not expected_file or expected_file["sha256"] != record["sha256"] or expected_file["bytes"] != record["bytes"]:
                raise ValueError("Manifest success differs from canonical file list: " + file_rel)
            if file_rel not in seen_paths:
                if file_path.stat().st_size != record["bytes"] or sha(file_path) != record["sha256"]:
                    raise ValueError("Source successful file failed size/SHA256: " + file_rel)
                source_files[file_rel] = {"file": file_rel, "sha256": record["sha256"], "bytes": record["bytes"]}
                seen_paths.add(file_rel)
            proof.update({"sourceFile": file_rel, "sourceSha256": record["sha256"], "sourceBytes": record["bytes"]})
            item = content.setdefault(record["sha256"], {"sha256": record["sha256"], "bytes": record["bytes"], "extension": record.get("extension", file_path.suffix).lower(),
                                     "source": file_path, "requestKeys": set(), "assetIDs": set(), "references": [], "sourceProofs": []})
            if item["bytes"] != record["bytes"]: raise ValueError("Hash repeated with a different byte count")
            item["requestKeys"].add(key)
            if record.get("id"): item["assetIDs"].add(str(record["id"]))
            item["references"].extend(refs)
            item["sourceProofs"].append(proof)
        manifest_data.append({"path": manifest_rel, "sha256": manifest_hash, "rejected": manifest.get("rejected", [])})
    if set(expected) != seen_paths:
        raise ValueError("Canonical physical files were not all verified: " + str(len(set(expected) - seen_paths)))
    if len(content) != canonical["verified_unique_sha256"] or sum(x["bytes"] for x in content.values()) != canonical["unique_bytes"]:
        raise ValueError("Unique source count/bytes differ from canonical")
    observed_effective = {r["key"]: (r["status"], r.get("http_status"), r.get("sha256")) for r in canonical["effective_requests"]}
    actual_effective = {key: (r["status"], r.get("httpStatus"), r.get("sha256")) for key, r in effective.items()}
    if observed_effective != actual_effective:
        raise ValueError("Final request states differ from canonical")
    if args.check_inputs_only:
        metadata = [{"path": relative(canonical_path, archive), "sha256": canonical_hash}, *source_proofs]
        for proof in metadata:
            if sha(archive / proof["path"]) != proof["sha256"]:
                raise ValueError("Bound source metadata changed during preflight")
            if proof.get("inventoryPath") and sha(archive / proof["inventoryPath"]) != proof["inventorySha256"]:
                raise ValueError("Bound source inventory changed during preflight")
        report = {"finishedUtc": now(), "passed": True, "mode": "check_inputs_only", "canonicalPath": relative(canonical_path, archive),
                  "canonicalSha256": canonical_hash, "game": {"placeId": canonical["placeId"], "universeId": canonical["universeId"]},
                  "verifiedPhysicalSourceFiles": len(source_files), "verifiedUniqueSha256": len(content),
                  "verifiedUniqueBytes": sum(item["bytes"] for item in content.values()), "finalRequestCount": len(effective),
                  "finalRequestStatuses": dict(collections.Counter(r["status"] for r in effective.values())),
                  "verifiedSourceMetadata": source_proofs, "sourceFiles": list(source_files.values()), "outputDirectoryCreated": False,
                  "copiesMade": 0, "luneCalls": 0, "networkRequests": 0, "archivedScriptExecutions": 0}
        write_json(evidence / "input-preflight-verification.json", report)
        print(json.dumps({k: v for k, v in report.items() if k != "sourceFiles"}, ensure_ascii=True), flush=True)
        return 0
    print(json.dumps({"event": "all_sources_verified", "physicalFiles": len(source_files), "uniqueSha256": len(content), "uniqueBytes": sum(x["bytes"] for x in content.values())}), flush=True)

    # Literal dependency parent links propagate root references without executing any downloaded data.
    ref_memo = {}
    def inherited_refs(key, stack=()):
        if key in ref_memo: return ref_memo[key]
        if key in stack: return []
        record = effective.get(key, {})
        found = list(record.get("references", []))
        for parent in record.get("parentKeys", []):
            for ref in inherited_refs(parent, stack + (key,)):
                found.append({**ref, "referenceRelation": "explicit_dependency_of", "dependencyParentKey": parent})
        ref_memo[key] = found
        return found

    containers = [x for x in content.values() if x["extension"] in {".rbxm", ".rbxmx"}]
    classifier_rows, observations = {}, []
    if containers and args.lune_executable:
        classifier_input = evidence / "container-input.json"
        classifier_report = evidence / "container-classification.json"
        write_json(classifier_input, {"containers": [{"path": str(x["source"]), "sha256": x["sha256"], "bytes": x["bytes"]} for x in containers]})
        helper = Path(__file__).resolve().with_name("classify_containers.luau")
        command = [str(args.lune_executable.resolve()), "run", str(helper), str(classifier_input), str(classifier_report)]
        observation = observed(command, evidence, "container-classification")
        observation.update({"helperSha256": sha(helper), "inputSha256": sha(classifier_input)})
        observations.append(observation)
        if observation["exitStatus"] == 0:
            report = load(classifier_report)
            classifier_rows = {r["sha256"]: r for r in report["containers"]}
            if set(classifier_rows) != {x["sha256"] for x in containers}:
                raise ValueError("Container classifier results do not match their exact inputs")
            observation["reportSha256"] = sha(classifier_report)

    files, copied_bytes, ext_counts, subtype_counts, class_counts = [], 0, collections.Counter(), collections.Counter(), collections.Counter()
    for checksum, item in sorted(content.items()):
        ext = item["extension"]
        observed_extension = magic_extension(item["source"])
        with item["source"].open("rb") as stream: first32 = stream.read(32)
        format_evidence = {"extension": ext, "magicRecognizedAs": observed_extension, "headerFirst32Hex": first32.hex(),
                           "storedExtensionDiffersFromHeader": bool(observed_extension and observed_extension != ext),
                           "extensionPolicy": "preserve stored raw suffix; recognized header controls broad media category"}
        container = classifier_rows.get(checksum)
        actual_ext = observed_extension or ext
        if actual_ext in {".png", ".jpg", ".dds"}: category, subtype, destination_dir = "textures", actual_ext[1:], "textures"
        elif actual_ext == ".mesh":
            category, subtype, destination_dir = "models", "roblox_mesh", "models/meshes"
            with item["source"].open("rb") as stream: header = stream.read(128).split(b"\n", 1)[0]
            format_evidence.update({"meshHeaderLiteral": header.decode("ascii", "replace"), "skeletonDataAssessment": "not decoded; raw mesh preserved; no rig/bone availability claim"})
        elif actual_ext in {".ogg", ".mp3"}: category, subtype, destination_dir = "audio", actual_ext[1:], "audio"
        elif ext in {".rbxm", ".rbxmx"}:
            classification = container.get("classification", "unclassified_container") if container else "unclassified_container"
            if classification == "animation_payload": category, subtype, destination_dir = "animations", "downloaded_keyframe_or_curve_container", "animations/downloaded"
            else: category, subtype, destination_dir = "other", classification, "other/downloaded-containers"
            if container:
                container = {k: v for k, v in container.items() if k != "sourcePath"}
                for animation in container.get("animations", []):
                    if isinstance(animation.get("poseNames"), list):
                        animation["poseNamesSha256"] = hashlib.sha256(json.dumps(animation["poseNames"], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                class_counts.update(container.get("classCounts", {}))
            else:
                container = {"classification": classification, "success": False, "error": "Optional Lune unavailable or classifier failed; bytes retained without inferred class"}
        elif actual_ext in {".ttf", ".otf"}: category, subtype, destination_dir = "other", "font", "other/fonts"
        elif actual_ext == ".json": category, subtype, destination_dir = "other", "json_metadata", "other/json"
        else: category, subtype, destination_dir = "other", "unclassified_raw", "other/unclassified"
        refs = []
        seen_refs = set()
        for key in sorted(item["requestKeys"]):
            for reference in inherited_refs(key):
                marker = json.dumps(reference, sort_keys=True, ensure_ascii=False)
                if marker not in seen_refs:
                    refs.append(reference)
                    seen_refs.add(marker)
        tags, uses, ref_paths = {"format:" + ext.lstrip("."), "category:" + category}, [], set()
        for reference in refs:
            new_tags, basis = usage(reference)
            tags.update(new_tags)
            if reference.get("path"): ref_paths.add(reference["path"])
            for entry in basis:
                uses.append({**entry, "path": reference.get("path"), "class": reference.get("class"), "property": reference.get("property"),
                             "inventoryPath": reference.get("inventoryPath"), "inventorySha256": reference.get("inventorySha256"),
                             "inventoryIndex": reference.get("inventoryIndex"), "referenceRelation": reference.get("referenceRelation")})
        if category == "animations": tags.add("animation:static-container-payload")
        paths_sorted = sorted(ref_paths)
        if paths_sorted:
            readable = "_".join(re.split(r"[.\\/]", paths_sorted[0])[-3:])
        elif container and container.get("rootNames"):
            readable = container["rootNames"][0]
        else:
            readable = item["source"].stem
        ids = sorted(item["assetIDs"], key=lambda x: (len(x), x))
        id_label = "asset" + ids[0] + ("_and" + str(len(ids) - 1) if len(ids) > 1 else "") if ids else "builtin-or-dependency"
        filename = safe_name(readable) + "__" + id_label + "__" + checksum[:8] + ext
        destination = output / destination_dir / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.stat().st_size != item["bytes"] or sha(destination) != checksum:
                raise ValueError("Existing destination differs; refused overwrite")
        else:
            with destination.open("xb") as out, item["source"].open("rb") as inp:
                shutil.copyfileobj(inp, out, 1024 * 1024)
        copied_hash = sha(destination)
        if copied_hash != checksum or destination.stat().st_size != item["bytes"]:
            raise ValueError("Copied library file failed hash/size verification")
        path = relative(destination, output)
        files.append({"relativePath": path, "filename": filename, "category": category, "subtype": subtype,
                      "tags": sorted(tags), "referencePaths": paths_sorted, "assetIDs": ids, "requestKeys": sorted(item["requestKeys"]),
                      "sha256": checksum, "bytes": item["bytes"], "extension": ext, "copiedFileSha256": copied_hash,
                      "sourceProofs": item["sourceProofs"], "references": refs, "usageEvidence": uses,
                      "formatEvidence": format_evidence, "containerClassification": container,
                      "copyVerification": {"sizeMatches": True, "sha256Matches": True}})
        ext_counts[ext] += 1
        subtype_counts[subtype] += 1
        copied_bytes += item["bytes"]
        if len(files) % 500 == 0:
            print(json.dumps({"event": "copy_progress", "copiedUniqueFiles": len(files), "copiedBytes": copied_bytes}), flush=True)
    if len(files) != len(content) or len({f["sha256"] for f in files}) != len(files):
        raise ValueError("Library did not retain exactly one copy per successful content SHA256")
    requests = []
    for key, record in sorted(effective.items()):
        requests.append({"key": key, "assetID": record.get("id"), "status": record["status"], "httpStatus": record.get("httpStatus"),
                         "uri": record.get("uri"), "error": record.get("error"), "sha256": record.get("sha256"),
                         "references": inherited_refs(key), "parentKeys": record.get("parentKeys", []), "history": histories[key]})
    canonical_relative = relative(canonical_path, archive)
    immutable_inputs = [{"path": canonical_relative, "sha256": canonical_hash}, *source_proofs]
    for proof in immutable_inputs:
        if sha(archive / proof["path"]) != proof["sha256"]:
            raise ValueError("Bound source metadata changed during extraction")
        if proof.get("inventoryPath") and sha(archive / proof["inventoryPath"]) != proof["inventorySha256"]:
            raise ValueError("Bound source inventory changed during extraction")
    summary = {"uniqueDownloadedContents": len(files), "copiedBytes": copied_bytes,
               "categoryCounts": dict(collections.Counter(f["category"] for f in files)), "subtypeCounts": dict(subtype_counts),
               "extensionCounts": dict(ext_counts), "containerClassCounts": dict(class_counts),
               "finalRequestCount": len(requests), "finalRequestStatuses": dict(collections.Counter(r["status"] for r in requests)),
               "finalHttpFailures": dict(collections.Counter(str(r["httpStatus"]) for r in requests if r.get("httpStatus"))),
               "oneFilePerUniqueContentSha256": True, "allSourceAndCopiedHashesVerified": True,
               "archiveMetadataUnchanged": True, "networkRequests": 0, "archivedScriptExecutions": 0}
    index = {"schemaVersion": 1, "kind": "classified_download_library", "generatedUtc": now(),
             "game": {"placeId": canonical["placeId"], "universeId": canonical["universeId"]},
             "pathBasis": "relativePath, sourceProofs.sourceFile, inventoryPath and manifestPath are relative to their stated root",
             "source": {"captureIdentity": {"placeId": canonical["placeId"], "universeId": canonical["universeId"], "canonicalSha256": canonical_hash},
                        "canonicalPath": canonical_relative, "canonicalSha256": canonical_hash,
                        "verifiedSourceMetadata": source_proofs, "verifiedPhysicalSourceFiles": len(source_files)},
             "classificationPolicy": {"usage": "observed class/property references; name-only music tags are candidates",
                                      "container": "optional data-only offline deserialization; failed/absent parser stays unclassified",
                                      "mesh": "raw header recorded; skeleton and rig structure not decoded",
                                      "unknown": "preserved under other; no executable archived script is imported"},
             "summary": summary, "files": files, "requests": requests, "rejectedReferences": manifest_data,
             "classifierExecution": [{k: v for k, v in row.items() if k in {"exitStatus", "startedUtc", "finishedUtc", "helperSha256", "inputSha256", "reportSha256"}} for row in observations]}
    write_json(output / "download-index.json", index)
    # Reopen the index and every copied file independently after publication.
    reopened = load(output / "download-index.json")
    for item in reopened["files"]:
        path = output / item["relativePath"]
        if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise ValueError("Published-index independent copy recheck failed")
    write_json(evidence / "download-library-verification.json", {"finishedUtc": now(), "passed": True, "downloadIndexSha256": sha(output / "download-index.json"),
               "summary": summary, "immutableSourceMetadata": immutable_inputs, "sourceFiles": list(source_files.values()),
               "reopenedCopiedFiles": len(files), "classifierExecution": observations})
    print(json.dumps({"event": "classified_library_complete", "index": str(output / "download-index.json"), "indexSha256": sha(output / "download-index.json"), "summary": summary}, ensure_ascii=False), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-inputs-only", action="store_true", help="Verify all bound metadata and source bytes; no output library, copies, Lune or network")
    parser.add_argument("--lune-executable", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    if args.output is None and not args.check_inputs_only:
        parser.error("--output is required unless --check-inputs-only is used")
    if args.evidence_dir is None:
        base = args.output or args.archive
        args.evidence_dir = base.resolve().parent / (base.name + "-download-input-evidence" if args.check_inputs_only else base.name + "-download-evidence")
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
