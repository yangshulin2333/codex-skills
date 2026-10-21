"""Verify the current client terrain capture as data, then copy it atomically."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import math
import argparse


CAPTURE = None
PLACE = None
UNIVERSE = None


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def integer(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value == int(value)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_hash(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def run_bounds(start, length, size, origin, resolution):
    last = start + length - 1
    dy, dz = size[1], size[2]
    x0, x1 = start // (dy * dz), last // (dy * dz)
    y0, y1 = (start // dz) % dy, (last // dz) % dy
    z0, z1 = start % dz, last % dz
    if x0 != x1:
        y0, y1, z0, z1 = 0, dy - 1, 0, dz - 1
    elif y0 != y1:
        z0, z1 = 0, dz - 1
    return ([origin[i] + v * resolution for i, v in enumerate((x0, y0, z0))],
            [origin[i] + (v + 1) * resolution for i, v in enumerate((x1, y1, z1))])


def merge_bounds(current, bounds):
    if current is None:
        return bounds
    return ([min(current[0][i], bounds[0][i]) for i in range(3)],
            [max(current[1][i], bounds[1][i]) for i in range(3)])


def validate():
    require((CAPTURE / "capture-complete.txt").is_file(), "Terrain capture completion marker missing")
    summary = read_json(CAPTURE / "capture-summary.json")
    start_report = read_json(CAPTURE / "capture-start.json")
    for report in (summary, start_report):
        require(report.get("placeId") == PLACE and report.get("universeId") == UNIVERSE, "Terrain target mismatch")
    require(summary.get("completeExplicitBox") is True, "Explicit scan box is incomplete")
    require(summary.get("completeWholeWorld") is False, "Unexpected global completeness claim")
    require(summary.get("gameObjectsModified") is False, "Unexpected terrain capture modification")
    minimum, maximum = summary["bounds"]["min"], summary["bounds"]["maxExclusive"]
    chunk, resolution = summary["chunkStuds"], summary["bounds"]["resolution"]
    require(finite(resolution) and resolution > 0, "Invalid terrain resolution")
    require(all(len(v) == 3 for v in (minimum, maximum, chunk)), "Invalid 3D capture bounds")
    require(all(integer(v) for vector in (minimum, maximum, chunk) for v in vector), "Noninteger grid coordinates")
    require(all(chunk[i] > 0 and maximum[i] > minimum[i] for i in range(3)), "Invalid capture extents")
    require(all(integer((maximum[i] - minimum[i]) / chunk[i]) and integer(chunk[i] / resolution) for i in range(3)), "Unaligned chunk grid")
    grid = [int((maximum[i] - minimum[i]) / chunk[i]) for i in range(3)]
    size = [int(v / resolution) for v in chunk]
    planned = math.prod(grid)
    voxels = math.prod(size)
    require(planned == summary["totals"]["plannedChunks"], "Planned chunk count mismatch")
    air = [value["value"] for value in summary["materials"].values() if value["name"] == "Air"]
    require(len(air) == 1, "Air material value unavailable or ambiguous")
    air_value = air[0]
    require(summary["index"] == "chunk-index.jsonl", "Unexpected index path")
    entries = [json.loads(line) for line in (CAPTURE / summary["index"]).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    require(len(entries) == planned, "Index does not cover every planned chunk")
    totals, materials, hashes = Counter(), Counter(), []
    global_filled = None
    present_files = set()
    for number, entry in enumerate(entries, 1):
        n = number - 1
        ix, remainder = divmod(n, grid[1] * grid[2])
        iy, iz = divmod(remainder, grid[2])
        origin = [minimum[i] + coordinate * chunk[i] for i, coordinate in enumerate((ix, iy, iz))]
        require(entry.get("index") == number and entry.get("origin") == origin, f"Chunk {number}: index/origin differs")
        require(entry.get("sizeInCells") == size and entry.get("ok") is True, f"Chunk {number}: failed or wrong dimensions")
        require(entry.get("voxels") == voxels, f"Chunk {number}: voxel count differs")
        totals["completedChunks"] += 1
        totals["scannedVoxels"] += voxels
        relative = entry.get("file")
        if relative is None:
            require(entry.get("empty") is True and all(entry.get(key) == 0 for key in ("nonemptyCells", "solidCells", "liquidCells", "nondefaultCells")), f"Chunk {number}: omitted data is not fully default")
            totals["emptyChunks"] += 1
            continue
        path = (CAPTURE / relative).resolve()
        require(path.is_relative_to(CAPTURE.resolve()) and path.is_file() and not path.is_symlink(), f"Chunk {number}: unsafe data path")
        require(relative not in present_files, f"Chunk {number}: duplicate chunk file")
        present_files.add(relative)
        data = read_json(path)
        require(data.get("schema") == "codex-terrain-rle-v2" and data.get("origin") == origin and data.get("size") == size and data.get("resolution") == resolution, f"Chunk {number}: data header differs")
        require(data.get("order") == "x-major,y-middle,z-fastest", f"Chunk {number}: unexpected voxel order")
        require(data.get("fields") == ["runLength", "Enum.Material.Value", "SolidOccupancy", "LiquidOccupancy"], f"Chunk {number}: channel field order differs")
        require(path.stat().st_size == entry["bytes"], f"Chunk {number}: JSON byte count differs")
        runs = data["runs"]
        require(len(runs) % 4 == 0 and len(runs) // 4 == entry["runs"], f"Chunk {number}: RLE record count differs")
        count, stats, filled, nondefault_bounds = 0, Counter(), None, None
        for offset in range(0, len(runs), 4):
            length, material, solid, liquid = runs[offset:offset + 4]
            require(integer(length) and length > 0 and count + length <= voxels, f"Chunk {number}: invalid run length")
            require(integer(material) and str(int(material)) in data["materials"], f"Chunk {number}: invalid/undeclared material")
            require(data["materials"][str(int(material))]["value"] == material, f"Chunk {number}: material mapping differs")
            require(finite(solid) and finite(liquid) and 0 <= solid <= 1 and 0 <= liquid <= 1, f"Chunk {number}: invalid channel value")
            length = int(length)
            has_solid, has_liquid = material != air_value and solid > 0, liquid > 0
            nondefault = material != air_value or solid != 0 or liquid != 0
            stats["solidCells"] += length if has_solid else 0
            stats["liquidCells"] += length if has_liquid else 0
            stats["nonemptyCells"] += length if has_solid or has_liquid else 0
            stats["nondefaultCells"] += length if nondefault else 0
            materials[str(int(material))] += length
            if has_solid or has_liquid:
                filled = merge_bounds(filled, run_bounds(count, length, size, origin, resolution))
            if nondefault:
                nondefault_bounds = merge_bounds(nondefault_bounds, run_bounds(count, length, size, origin, resolution))
            count += length
        require(count == voxels and stats["nondefaultCells"] > 0 and entry.get("empty") is False, f"Chunk {number}: RLE does not preserve the entire nondefault chunk")
        for name in ("solidCells", "liquidCells", "nonemptyCells", "nondefaultCells"):
            require(stats[name] == entry[name] == data[name], f"Chunk {number}: {name} differs from reconstructed RLE")
            totals[name] += stats[name]
        expected_filled = (data.get("filledMin"), data.get("filledMaxExclusive"))
        require(expected_filled == (None, None) if filled is None else list(expected_filled) == list(filled), f"Chunk {number}: filled bounds differ")
        require(list((data["dataMin"], data["dataMaxExclusive"])) == list(nondefault_bounds), f"Chunk {number}: nondefault data bounds differ")
        if filled:
            global_filled = merge_bounds(global_filled, filled)
        totals["nonemptyChunks"] += 1
        hashes.append({"file": relative, "bytes": path.stat().st_size, "sha256": file_hash(path), "rleRecords": len(runs) // 4})
    totals["failedChunks"] = 0
    totals["plannedChunks"] = planned
    for name, expected in summary["totals"].items():
        require(totals[name] == expected, f"Capture summary {name} differs from index/RLE")
    require(([None, None] if global_filled is None else list(global_filled)) == [summary.get("filledMin"), summary.get("filledMaxExclusive")], "Global filled bounds differ")
    actual_files = {path.relative_to(CAPTURE).as_posix() for path in (CAPTURE / "chunks").rglob("*.json")}
    require(actual_files == present_files, "Chunk folder and index file sets differ")
    return {"placeId": PLACE, "universeId": UNIVERSE, "passed": True,
            "scope": "All indexed chunks in the explicit capture box; no whole-world completeness claim",
            "bounds": summary["bounds"], "verifiedTotals": dict(totals),
            "checkedChunks": totals["completedChunks"],
            "countedNonempty": totals["nonemptyCells"], "countedSolid": totals["solidCells"],
            "countedLiquid": totals["liquidCells"], "errors": [],
            "filledMin": global_filled[0] if global_filled else None, "filledMaxExclusive": global_filled[1] if global_filled else None,
            "CountCellsBefore": summary["CountCellsBefore"], "CountCellsAfter": summary["CountCellsAfter"],
            "CountCellsComparisonIsGlobalProof": False,
            "captureSummarySha256": file_hash(CAPTURE / "capture-summary.json"),
            "chunkIndexSha256": file_hash(CAPTURE / summary["index"]), "verifiedChunkFiles": hashes,
            "archiveScriptsExecuted": False, "onlineTerrainModified": False}


def main():
    global CAPTURE, PLACE, UNIVERSE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--place-id", type=int, required=True)
    parser.add_argument("--universe-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    CAPTURE, PLACE, UNIVERSE = args.capture.resolve(), args.place_id, args.universe_id
    report = validate()
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in report.items() if key != "verifiedChunkFiles"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
