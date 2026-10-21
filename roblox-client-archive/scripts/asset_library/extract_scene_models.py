"""Extract nonoverlapping Roblox XML model bundles, rigs and embedded animation.

Data only: no GUI, network, scene/script execution, or bytecode decompilation.
Model and WorldModel subtrees are copied once; nested models get exact indexes.
Roblox script classes and Source properties are removed. Reference links crossing
the output boundary are documented and cleared. SharedString dependencies remain.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

MODEL_CLASSES = {"Model", "WorldModel"}
SCRIPT_CLASSES = {"Script", "LocalScript", "ModuleScript", "CoreScript", "AuroraScript", "LuaSourceContainer"}
PART_CLASSES = {"Part", "MeshPart", "UnionOperation", "NegateOperation", "PartOperation", "WedgePart", "CornerWedgePart", "TrussPart", "Seat", "VehicleSeat", "SpawnLocation"}
CONTENT_PROPERTIES = {"MeshId", "MeshContent", "TextureID", "TextureId", "Texture", "TextureContent", "Image", "ImageContent", "SoundId", "AudioContent", "AnimationId", "AnimationContent", "ColorMap", "ColorMapContent", "MetalnessMap", "MetalnessMapContent", "NormalMap", "NormalMapContent", "RoughnessMap", "RoughnessMapContent", "ShirtTemplate", "PantsTemplate", "Graphic", "Video", "VideoContent", "FontFace", "ReferenceMeshId", "CageMeshId", "LinkedSource", "SkyboxBk", "SkyboxDn", "SkyboxFt", "SkyboxLf", "SkyboxRt", "SkyboxUp"}
RIG_CLASSES = {"Bone", "Motor6D", "AnimationController", "Animator", "Humanoid"}


def json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")


def metadata(path):
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"bytes": path.stat().st_size, "sha256": checksum}


def item_name(item):
    props = item.find("Properties")
    if props is not None:
        for prop in props:
            if prop.get("name") == "Name":
                return "".join(prop.itertext())
    return item.get("class", "")


def source_path(frame):
    parts = []
    while frame:
        parts.append({"name": frame["name"], "class": frame["class"], "siblingOrdinal": frame["ordinal"]})
        frame = frame["parent"]
    return list(reversed(parts))


def dotted(path):
    return ".".join(piece["name"] for piece in path)


def safe_stem(value):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")[:55] or "unnamed"


def walk_items(root_item):
    def recurse(item, path):
        counts = Counter()
        yield item, path
        for child in item.findall("Item"):
            identity = (item_name(child), child.get("class", ""))
            counts[identity] += 1
            piece = {"name": identity[0], "class": identity[1], "siblingOrdinal": counts[identity]}
            yield from recurse(child, path + [piece])
    piece = {"name": item_name(root_item), "class": root_item.get("class", ""), "siblingOrdinal": 1}
    yield from recurse(root_item, [piece])


def content_uris(prop):
    name = prop.get("name", "")
    if name in CONTENT_PROPERTIES or prop.tag in {"Content", "ContentId", "Font"}:
        for value in prop.itertext():
            value = value.strip()
            if value.startswith(("rbxassetid://", "rbxasset://", "rbxthumb://", "http://", "https://")):
                yield value


def part_bounds(item):
    props = item.find("Properties")
    if props is None:
        return None
    values = {prop.get("name"): prop for prop in props}
    cf, size = values.get("CFrame"), values.get("Size")
    if cf is None or size is None:
        return None
    try:
        center = [float(cf.findtext(axis)) for axis in ("X", "Y", "Z")]
        half = [abs(float(size.findtext(axis))) / 2 for axis in ("X", "Y", "Z")]
        rotation = [[float(cf.findtext(f"R{row}{col}")) for col in range(3)] for row in range(3)]
        extent = [sum(abs(rotation[row][col]) * half[col] for col in range(3)) for row in range(3)]
        low = [center[i] - extent[i] for i in range(3)]
        high = [center[i] + extent[i] for i in range(3)]
        if not all(math.isfinite(value) for value in low + high):
            return None
        return low, high
    except (ValueError, TypeError):
        return None


def nested_rig_indexes(models, rigs):
    rig_models = []
    containers = {}
    key = lambda path: json.dumps(path, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for bundle in models:
        lookup = {key(model["relativePath"]): model for model in bundle["models"]}
        counts = {name: Counter() for name in lookup}
        for node in bundle["rigNodes"]:
            path = node["relativePath"]
            for stop in range(1, len(path) + 1):
                name = key(path[:stop])
                if name in counts:
                    counts[name][node["class"]] += 1
        for name, model in lookup.items():
            model["rigClassCounts"] = dict(counts[name])
            model["hasRig"] = bool(counts[name]["Bone"] or counts[name]["Motor6D"])
            if model["hasRig"]:
                rig_models.append({"containerPath": bundle["file"], "containerSha256": bundle["sha256"],
                                   "relativePath": model["relativePath"], "sourceTreePath": model["sourceTreePath"],
                                   "rigClassCounts": model["rigClassCounts"], "skinWeightsVerified": False,
                                   "animationPoseMappingVerified": False})
        containers[bundle["file"]] = bundle
    for rig in rigs:
        rig["models"] = containers[rig["containerFile"]]["models"]
    return rig_models


def stage_bundle(item, kind, ordinal, original_path, staging, records, model_origins, animation_occurrences):
    """Normalize referents in a self-contained copy, without touching source tree."""
    item = copy.deepcopy(item)
    nodes = list(walk_items(item))
    old_to_new = {}
    for index, (node, _) in enumerate(nodes):
        old = node.get("referent")
        if old is not None:
            if old in old_to_new:
                raise RuntimeError("Duplicate referent in source bundle")
            old_to_new[old] = f"RBX{index}"
    classes = Counter(node.get("class", "") for node, _ in nodes)
    if set(classes) & SCRIPT_CLASSES:
        raise RuntimeError("A script object survived stripping")
    external = []
    dependencies = []
    shared_ids = set()
    rig_nodes = []
    animation_refs = []
    model_entries = []
    bounds_low = [math.inf] * 3
    bounds_high = [-math.inf] * 3
    bounds_parts = bounds_skipped = 0
    internal_refs = 0
    for node, relative_path in nodes:
        old = node.get("referent")
        cls = node.get("class", "")
        if cls in MODEL_CLASSES:
            origin = model_origins.get(old)
            model_entries.append({"originalReferent": old, "sourcePath": origin,
                                  "relativePath": relative_path, "class": cls})
        if cls in RIG_CLASSES:
            rig_nodes.append({"class": cls, "name": item_name(node), "relativePath": relative_path,
                              "sourceReferent": old})
        if cls in PART_CLASSES:
            bounds = part_bounds(node)
            if bounds is None:
                bounds_skipped += 1
            else:
                low, high = bounds
                bounds_parts += 1
                for i in range(3):
                    bounds_low[i] = min(bounds_low[i], low[i])
                    bounds_high[i] = max(bounds_high[i], high[i])
        props = node.find("Properties")
        if props is not None:
            for prop in props:
                if prop.get("name") == "Source" or prop.tag == "ProtectedString":
                    raise RuntimeError("A Source/ProtectedString property survived stripping")
                if prop.tag == "Ref":
                    target = (prop.text or "").strip()
                    if target not in {"", "null", "nil"}:
                        if target in old_to_new:
                            prop.text = old_to_new[target]
                            internal_refs += 1
                        else:
                            external.append({"ownerPath": relative_path, "ownerSourceReferent": old,
                                             "property": prop.get("name"), "targetSourceReferent": target,
                                             "action": "cleared_to_null"})
                            prop.text = "null"
                if prop.tag == "SharedString":
                    shared_ids.add((prop.text or "").strip())
                for uri in content_uris(prop):
                    dependencies.append({"uri": uri, "ownerPath": relative_path,
                                         "class": cls, "property": prop.get("name")})
                    if cls == "Animation":
                        animation_refs.append({"uri": uri, "relativePath": relative_path,
                                               "note": "Reference only; not proof the action data was acquired"})
        if old is not None:
            node.set("referent", old_to_new[old])
    blob = ET.tostring(item, encoding="utf-8", short_empty_elements=True)
    content_sha = hashlib.sha256(blob).hexdigest()
    stem = f"{ordinal:05d}-{safe_stem(original_path[-1]['name'])}-{content_sha[:12]}"
    stage_path = staging / (stem + ".item.xml")
    with stage_path.open("xb") as stream:
        stream.write(blob)
    record = {"kind": kind, "stage": stage_path.name, "stem": stem, "itemSha256": content_sha,
              "sourcePath": original_path, "sourcePathText": dotted(original_path), "instances": len(nodes),
              "classCounts": dict(classes), "models": model_entries, "rigNodes": rig_nodes,
              "rigClassCounts": {cls: classes[cls] for cls in sorted(RIG_CLASSES)},
              "animationReferences": animation_refs, "dependencyUris": sorted({row['uri'] for row in dependencies}),
              "dependencyReferences": dependencies, "sharedStringIds": sorted(shared_ids),
              "internalRefsPreserved": internal_refs, "externalRefsCleared": external,
              "bounds": {"type": "world-axis-aligned bounds from Part CFrame rotation and Size",
                         "min": bounds_low if bounds_parts else None, "max": bounds_high if bounds_parts else None,
                         "partsCovered": bounds_parts, "partsSkipped": bounds_skipped,
                         "meshSurfaceBoundsVerified": False}, "poseNames": sorted({item_name(node) for node, _ in nodes if node.get('class') == 'Pose'})}
    if kind == "animation":
        times = []
        for node, _ in nodes:
            if node.get("class") == "Keyframe":
                properties = node.find("Properties")
                prop = next((prop for prop in properties if prop.get("name") == "Time"), None) if properties is not None else None
                try:
                    times.append(float(prop.text))
                except (ValueError, TypeError, AttributeError):
                    pass
        record["animation"] = {"class": item.get("class"), "keyframes": classes["Keyframe"], "poses": classes["Pose"],
                               "timeMin": min(times) if times else None, "timeMax": max(times) if times else None,
                               "rigMappingVerified": False, "playbackVerified": False}
        animation_occurrences.append(record)
    records.append(record)


def extract(source, output, work):
    before = metadata(source)
    staging = work / "scene-tools" / "staging"
    staging.mkdir(parents=True, exist_ok=False)
    assembled = output / "models" / "assembled"
    animation_dir = output / "animations" / "scene"
    rig_dir = output / "rigs"
    for directory in (assembled, animation_dir, rig_dir):
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.iterdir()):
            raise RuntimeError("Refusing nonempty output directory: " + str(directory))
    records = []
    model_origins = {}
    source_classes = Counter()
    removed_scripts = Counter()
    stripped_properties = Counter()
    promoted_children = []
    frames = []
    element_stack = []
    shared_strings = {}
    animation_occurrences = []
    model_ordinal = animation_ordinal = loose_ordinal = 0
    for event, element in ET.iterparse(source, events=("start", "end")):
        if event == "start":
            element_stack.append(element)
            if element.tag == "Item":
                cls = element.get("class", "")
                parent = frames[-1] if frames else None
                if parent:
                    parent["childCount"] += 1
                frame = {"class": cls, "name": cls, "parent": parent, "ordinal": parent["childCount"] if parent else 1,
                         "childCount": 0, "element": element,
                         "hasModelAncestor": bool(parent and (parent["class"] in MODEL_CLASSES or parent["hasModelAncestor"]))}
                frames.append(frame)
                source_classes[cls] += 1
            continue
        if element.tag == "Properties" and frames:
            frame = frames[-1]
            for prop in list(element):
                if prop.get("name") == "Name":
                    frame["name"] = "".join(prop.itertext())
                if prop.get("name") == "Source" or prop.tag == "ProtectedString":
                    stripped_properties[prop.get("name", prop.tag)] += 1
                    element.remove(prop)
        elif element.tag == "Item":
            frame = frames.pop()
            cls = frame["class"]
            path = source_path(frame)
            if cls in MODEL_CLASSES:
                model_origins[element.get("referent")] = path
            if cls in SCRIPT_CLASSES:
                removed_scripts[cls] += 1
                parent_element = frame["parent"]["element"] if frame["parent"] else element_stack[-2]
                children = list(element.findall("Item"))
                at = list(parent_element).index(element)
                parent_element.remove(element)
                for child in children:
                    parent_element.insert(at, child)
                    at += 1
                if children:
                    promoted_children.append({"removedScriptPath": path, "childrenPromoted": len(children)})
            elif cls in {"KeyframeSequence", "CurveAnimation"}:
                animation_ordinal += 1
                stage_bundle(element, "animation", animation_ordinal, path, staging, records, model_origins, animation_occurrences)
            if cls in MODEL_CLASSES and not frame["hasModelAncestor"]:
                model_ordinal += 1
                stage_bundle(element, "model", model_ordinal, path, staging, records, model_origins, animation_occurrences)
                parent_element = frame["parent"]["element"] if frame["parent"] else element_stack[-2]
                parent_element.remove(element)
                element.clear()
            elif frame["parent"] is None and cls not in SCRIPT_CLASSES:
                remaining_classes = Counter(node.get("class", "") for node in element.iter("Item"))
                if any(remaining_classes[c] for c in PART_CLASSES | RIG_CLASSES | {"Animation", "KeyframeSequence", "CurveAnimation", "SpecialMesh"}):
                    loose_ordinal += 1
                    service_folder = ET.Element("Item", {"class": "Folder", "referent": "LOOSE_SERVICE"})
                    props = ET.SubElement(service_folder, "Properties")
                    ET.SubElement(props, "string", {"name": "Name"}).text = frame["name"] + "_loose_objects"
                    for child in element.findall("Item"):
                        service_folder.append(child)
                    stage_bundle(service_folder, "loose_geometry", loose_ordinal, path, staging, records, model_origins, animation_occurrences)
                element.clear()
        elif element.tag == "SharedString" and not frames:
            key = element.get("md5")
            if key:
                if key in shared_strings:
                    raise RuntimeError("Duplicate global SharedString key")
                shared_strings[key] = copy.deepcopy(element)
            element.clear()
        element_stack.pop()
    if metadata(source) != before:
        raise RuntimeError("Source changed during extraction")
    models = []
    rigs = []
    animations = []
    content_seen = {}
    non_animation_class_counts = Counter()
    bundle_instances = 0
    for record in records:
        kind = record["kind"]
        folder = animation_dir if kind == "animation" else assembled
        relative_folder = folder.relative_to(output).as_posix()
        dedup_key = (kind, record["itemSha256"])
        if kind == "animation" and dedup_key in content_seen:
            existing = content_seen[dedup_key]
            occurrence = {"sourcePath": record["sourcePath"], "sourcePathText": record["sourcePathText"]}
            existing["occurrences"].append(occurrence)
            record["file"] = existing["file"]
            continue
        filename = record["stem"] + ".rbxmx"
        path = folder / filename
        doc = ET.Element("roblox", {"version": "4"})
        ET.SubElement(doc, "External").text = "null"
        ET.SubElement(doc, "External").text = "nil"
        stage_path = staging / record["stage"]
        item = ET.parse(stage_path).getroot()
        doc.append(item)
        if record["sharedStringIds"]:
            shared_root = ET.SubElement(doc, "SharedStrings")
            for key in record["sharedStringIds"]:
                if key not in shared_strings:
                    raise RuntimeError("Missing SharedString dependency: " + key)
                shared_root.append(copy.deepcopy(shared_strings[key]))
        with path.open("xb") as stream:
            stream.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
            ET.ElementTree(doc).write(stream, encoding="utf-8", xml_declaration=False, short_empty_elements=True)
        record["file"] = relative_folder + "/" + filename
        record["path"] = record["file"]
        record.update(metadata(path))
        record.pop("stage", None)
        if kind == "animation":
            record["occurrences"] = [{"sourcePath": record["sourcePath"], "sourcePathText": record["sourcePathText"]}]
            animations.append(record)
            content_seen[dedup_key] = record
        else:
            non_animation_class_counts.update(record["classCounts"])
            bundle_instances += record["instances"]
            models.append(record)
            for nested in record["models"]:
                nested["containerFile"] = record["file"]
                nested["containerPath"] = record["file"]
                nested["sourceTreePath"] = nested["sourcePath"]
            # Rig indexes point to assembled containers; no second model copy.
            if record["classCounts"].get("Bone", 0) or record["classCounts"].get("Motor6D", 0):
                rigs.append({"containerFile": record["file"], "containerSha256": record["sha256"],
                             "containerPath": record["file"],
                             "sourcePath": record["sourcePath"], "sourcePathText": record["sourcePathText"],
                             "rigClassCounts": record["rigClassCounts"], "nodes": record["rigNodes"],
                             "models": record["models"], "bounds": record["bounds"],
                             "skinWeightsVerified": False, "animationPoseMappingVerified": False})
    nested_model_count = sum(len(record["models"]) for record in models)
    source_models = sum(source_classes[cls] for cls in MODEL_CLASSES)
    if nested_model_count != source_models:
        raise RuntimeError(f"Not every source Model/WorldModel indexed: {nested_model_count} / {source_models}")
    for cls in ["Bone", "Motor6D", "KeyframeSequence", "Keyframe", "Pose"]:
        if non_animation_class_counts[cls] != source_classes[cls]:
            raise RuntimeError(f"Assembled bundle coverage mismatch for {cls}: {non_animation_class_counts[cls]} / {source_classes[cls]}")
    if sum(len(row["occurrences"]) for row in animations) != source_classes["KeyframeSequence"] + source_classes["CurveAnimation"]:
        raise RuntimeError("Embedded animation occurrence coverage mismatch")
    source_meta = {"path": str(source), **before}
    portable_source_meta = {"relativePath": source.parent.name + "/" + source.name, **before}
    rig_models = nested_rig_indexes(models, rigs)
    summary = {"source": source_meta, "outputRoot": str(output), "mode": "Offline original XML model extraction",
               "modelBundleFiles": len(models), "maximalModelBundleFiles": sum(row['kind'] == 'model' for row in models),
               "looseGeometryBundleFiles": sum(row['kind'] == 'loose_geometry' for row in models),
               "sourceModelObjects": source_models, "indexedModelObjects": nested_model_count,
               "rigContainerFiles": len(rigs), "embeddedAnimationOccurrences": sum(len(row['occurrences']) for row in animations),
               "nestedRigModelObjects": len(rig_models),
               "uniqueAnimationFiles": len(animations), "assembledClassCounts": dict(non_animation_class_counts),
               "sourceClassCounts": dict(source_classes), "removedScriptClasses": dict(removed_scripts),
               "strippedProperties": dict(stripped_properties), "scriptChildrenPromoted": promoted_children,
               "allModelObjectsIndexed": True, "assembledSkeletonAndPoseCountsMatchSource": True,
               "sourceHashStable": True, "scriptsExecuted": False, "sourceDecompiled": False,
               "limits": ["Maximum model bundles can contain many nested reusable models; use relativePath index to locate submodels",
                   "External object references are explicitly recorded and cleared; cross-container behavior is not restored",
                   "Original content URIs remain dependencies; the extraction does not rewrite mesh/texture/audio links",
                   "Bone/Motor6D presence preserves structure, not proof of complete mesh skin weights or playback",
                   "Animation references are not acquired motion data; only embedded KeyframeSequence/CurveAnimation objects are extracted here",
                   "Bounding boxes use saved Part CFrame and Size, not actual decoded mesh surface bounds",
                   "XML structure/hash verification does not constitute Studio import/render/playback verification"]}
    json_write(assembled / "index.json", {"schemaVersion": 1, "source": portable_source_meta, "bundles": models,
               "selectionRule": "Maximal non-overlapping Model/WorldModel subtrees plus remaining loose geometry/rig/reference folders"})
    json_write(rig_dir / "index.json", {"schemaVersion": 1, "source": portable_source_meta, "rigs": rigs,
               "rigModels": rig_models, "rigModelCount": len(rig_models),
               "copyRule": "Index references assembled bundle; no duplicate model copy"})
    json_write(animation_dir / "index.json", {"schemaVersion": 1, "source": portable_source_meta, "animations": animations,
               "deduplicationRule": "Normalized XML item bytes SHA256; retain all source occurrences"})
    json_write(work / "scene-extraction.json", {"schemaVersion": 1, "source": source_meta, "outputRoot": str(output), "summary": summary,
               "indexes": {"models": str(assembled / "index.json"), "rigs": str(rig_dir / "index.json"), "animations": str(animation_dir / "index.json")}})
    print(json.dumps({key: value for key, value in summary.items()
                      if key not in {"scriptChildrenPromoted", "sourceClassCounts", "assembledClassCounts"}}, ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path,
                        help="New work directory; default is a sibling output-name + -scene-work directory")
    args = parser.parse_args()
    output = args.output_root.resolve()
    work = args.work_root.resolve() if args.work_root else output.parent / (output.name + "-scene-work")
    extract(args.source.resolve(), output, work)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
