"""Independently verify extracted XML models, references, skeletons and hashes."""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

SCRIPT_CLASSES = {"Script", "LocalScript", "ModuleScript", "CoreScript", "AuroraScript", "LuaSourceContainer"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect_file(path, expected):
    if path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]:
        raise RuntimeError("Output size/SHA256 mismatch: " + str(path))
    root = ET.parse(path).getroot()
    if root.tag != "roblox" or root.get("version") != "4":
        raise RuntimeError("Invalid Roblox XML model document")
    items = list(root.iter("Item"))
    counts = Counter(item.get("class", "") for item in items)
    if dict(counts) != expected["classCounts"] or len(items) != expected["instances"]:
        raise RuntimeError("Output object/class counts differ from extraction index")
    if set(counts) & SCRIPT_CLASSES:
        raise RuntimeError("Script objects remain")
    ids = [item.get("referent") for item in items]
    if len(ids) != len(set(ids)) or None in ids:
        raise RuntimeError("Missing or duplicate referent")
    referents = set(ids)
    references = external_null = 0
    for prop in root.iter():
        if prop.get("name") == "Source" or prop.tag == "ProtectedString":
            raise RuntimeError("Script/bytecode Source property remains")
        if prop.tag == "Ref":
            value = (prop.text or "").strip()
            if value not in {"", "null", "nil"}:
                if value not in referents:
                    raise RuntimeError("Dangling internal reference in output")
                references += 1
            else:
                external_null += 1
    if references != expected["internalRefsPreserved"]:
        raise RuntimeError("Internal reference count mismatch")
    definitions = {row.get("md5") for row in root.findall("SharedStrings/SharedString")}
    used = {(prop.text or "").strip() for item in items for prop in item.findall("Properties/SharedString")}
    if used != definitions or used != set(expected["sharedStringIds"]):
        raise RuntimeError("SharedString dependency set mismatch")
    return {"file": expected["file"], "bytes": path.stat().st_size, "sha256": expected["sha256"],
            "instances": len(items), "classCounts": dict(counts), "internalRefs": references,
            "sharedStrings": len(definitions), "scriptsAbsent": True, "parsed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output_root.resolve()
    if args.report.exists():
        raise RuntimeError("Refusing to overwrite a verification report")
    load = lambda path: json.loads(path.read_text(encoding="utf-8-sig"))
    models = load(output / "models/assembled/index.json")
    animations = load(output / "animations/scene/index.json")
    rigs = load(output / "rigs/index.json")
    source_meta = models["source"]
    if (source_meta.get("path") is not None and str(source) != source_meta["path"]) or source.stat().st_size != source_meta["bytes"] or digest(source) != source_meta["sha256"]:
        raise RuntimeError("Original scene changed")
    total = Counter()
    checked = []
    for record in models["bundles"]:
        file = (output / record["file"]).resolve()
        if not file.is_relative_to(output):
            raise RuntimeError("Indexed path escaped library")
        checked.append(inspect_file(file, record))
        total.update(record["classCounts"])
    for record in animations["animations"]:
        checked.append(inspect_file(output / record["file"], record))
    source_counts = Counter()
    for _, element in ET.iterparse(source, events=("end",)):
        if element.tag == "Item":
            source_counts[element.get("class", "")] += 1
        element.clear()
    watched = ["Model", "WorldModel", "Bone", "Motor6D", "KeyframeSequence", "Keyframe", "Pose", "CurveAnimation"]
    for cls in watched:
        if total[cls] != source_counts[cls]:
            raise RuntimeError(f"Independent source/bundle count mismatch for {cls}: {total[cls]} / {source_counts[cls]}")
    lookup = {record["file"]: record for record in models["bundles"]}
    for rig in rigs["rigs"]:
        record = lookup[rig["containerFile"]]
        if record["sha256"] != rig["containerSha256"] or record["rigClassCounts"] != rig["rigClassCounts"]:
            raise RuntimeError("Rig index does not point to matching assembled model")
    if sum(len(record["occurrences"]) for record in animations["animations"]) != source_counts["KeyframeSequence"] + source_counts["CurveAnimation"]:
        raise RuntimeError("Animation source occurrence coverage differs")
    report = {"status": "passed", "source": source_meta, "outputRoot": str(output), "filesVerified": len(checked),
              "allXmlParsed": True, "allHashesVerified": True, "allInternalRefsResolve": True,
              "allSharedStringDependenciesIncluded": True, "scriptsAndSourceAbsent": True,
              "independentCounts": {cls: {"source": source_counts[cls], "assembled": total[cls]} for cls in watched},
              "rigIndexMatchesContainers": True, "animationOccurrencesCovered": True, "scriptsExecuted": False,
              "files": checked}
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in report.items() if key != "files"}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
