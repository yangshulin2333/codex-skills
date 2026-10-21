"""Verify all download-index content after copying/moving a library; no network or code execution."""
import argparse
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def confined(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Index path escaped its declared root: " + name)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--archive", type=Path, help="Optional immutable raw capture for independent source proof rechecks")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = args.library.resolve()
    index_path = root / "download-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    errors, checks, source_cache, seen_hashes, seen_destinations = [], collections.Counter(), {}, set(), set()
    archive = args.archive.resolve() if args.archive else None
    if archive:
        source = index["source"]
        canonical = confined(archive, source["canonicalPath"])
        if sha(canonical) != source["canonicalSha256"]:
            errors.append("Source canonical hash differs")
        for record in source["verifiedSourceMetadata"]:
            if sha(confined(archive, record["path"])) != record["sha256"] or sha(confined(archive, record["inventoryPath"])) != record["inventorySha256"]:
                errors.append("Source manifest/inventory hash differs: " + record["path"])
    for item in index["files"]:
        try:
            path = confined(root, item["relativePath"])
            if item["relativePath"] in seen_destinations or item["sha256"] in seen_hashes:
                raise ValueError("Repeated content SHA256 or destination")
            seen_destinations.add(item["relativePath"])
            seen_hashes.add(item["sha256"])
            if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"] or item["copiedFileSha256"] != item["sha256"]:
                raise ValueError("Copied size/hash mismatch")
            checks["copiedFiles"] += 1
            checks["copiedBytes"] += item["bytes"]
            if archive:
                for proof in item["sourceProofs"]:
                    original = confined(archive, proof["sourceFile"])
                    if proof["sourceFile"] not in source_cache:
                        source_cache[proof["sourceFile"]] = (original.stat().st_size, sha(original))
                    if source_cache[proof["sourceFile"]] != (proof["sourceBytes"], proof["sourceSha256"]) or proof["sourceSha256"] != item["sha256"]:
                        raise ValueError("Source byte/hash differs")
            checks["animationPayloadContainers"] += item["category"] == "animations"
        except Exception as error:
            errors.append({"file": item["relativePath"], "error": str(error)})
    if len(seen_hashes) != index["summary"]["uniqueDownloadedContents"] or checks["copiedBytes"] != index["summary"]["copiedBytes"]:
        errors.append("Published summary differs from verified copied content")
    owned = ["textures", "models/meshes", "audio", "animations/downloaded", "other"]
    actual = {path.relative_to(root).as_posix() for directory in owned for path in (root / directory).rglob("*") if path.is_file()}
    if actual != seen_destinations:
        errors.append({"error": "Owned directories do not contain exactly their indexed raw content",
                       "unindexed": sorted(actual - seen_destinations), "missing": sorted(seen_destinations - actual)})
    report = {"verifiedUtc": dt.datetime.now(dt.timezone.utc).isoformat(), "passed": not errors, "indexSha256": sha(index_path),
              "checks": dict(checks), "sourcePhysicalFilesChecked": len(source_cache), "errors": errors,
              "networkRequests": 0, "archivedScriptExecutions": 0}
    if args.report:
        with args.report.resolve().open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=True))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
