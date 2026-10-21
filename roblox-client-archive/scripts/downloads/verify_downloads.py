#!/usr/bin/env python3
"""Independently check inventory binding, request coverage, content, and file hashes."""
from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import urllib.parse


URI_RE = re.compile(r'''(?:rbx(?:asset(?:id)?|thumb)://[^\s<>"']+|https?://[^\s<>"']+)''', re.I)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def key_for(uri, asset_id=None):
    """Independent normalization of the downloader's documented request keys."""
    uri = str(uri or "").strip().replace("&amp;", "&")
    if uri.lower().startswith("rbxthumb://"):
        q = {k.lower(): v[0] for k, v in urllib.parse.parse_qs(uri[11:]).items()}
        kind, identifier = q.get("type", "").lower(), q.get("id", "")
        width, height = q.get("w", "420"), q.get("h", "420")
        if kind not in {"asset", "avatarheadshot", "avatarbust", "avatar", "gamepass"} or not all(x.isdigit() and int(x) > 0 for x in (identifier, width, height)):
            return None
        return "thumbnail:" + kind + ":" + str(int(identifier)) + ":" + str(int(width)) + "x" + str(int(height))
    if asset_id is not None and str(asset_id).isdigit() and int(asset_id) > 0:
        return "id:" + str(int(asset_id))
    m = re.fullmatch(r"rbxassetid://(\d+)", uri, re.I)
    if m and int(m[1]) > 0:
        return "id:" + str(int(m[1]))
    if uri.lower().startswith("rbxasset://"):
        return "builtin:" + urllib.parse.unquote(uri[11:]).replace("\\", "/").lower()
    try:
        parsed = urllib.parse.urlsplit(uri)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None or parsed.port not in {None, 443} or not any(host == d or host.endswith("." + d) for d in ("roblox.com", "rbxcdn.com")):
            return None
        q = {k.lower(): v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        aid = q.get("id", "")
        if aid.isdigit() and int(aid) > 0 and "asset" in parsed.path.lower():
            return "id:" + str(int(aid))
        normalized = urllib.parse.urlunsplit(("https", parsed.netloc.lower(), parsed.path, parsed.query, ""))
        return "url:" + hashlib.sha256(normalized.encode()).hexdigest()
    except ValueError:
        return None


def check_content(path, extension):
    """Magic/error-body checks, not a full media decoder or Studio rendering test."""
    with path.open("rb") as stream:
        head = stream.read(2048)
    if not head:
        raise ValueError("empty successful asset")
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    stripped = head.lstrip()
    if stripped.lower().startswith((b"<html", b"<!doctype html")):
        raise ValueError("HTML document is not a successful asset")
    checks = {
        ".png": lambda: head.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": lambda: head.startswith(b"\xff\xd8\xff"),
        ".jpeg": lambda: head.startswith(b"\xff\xd8\xff"),
        ".gif": lambda: head.startswith((b"GIF87a", b"GIF89a")),
        ".webp": lambda: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
        ".wav": lambda: head[:4] == b"RIFF" and head[8:12] == b"WAVE",
        ".ogg": lambda: head.startswith(b"OggS"),
        ".mp3": lambda: head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
        ".otf": lambda: head.startswith(b"OTTO"),
        ".ttf": lambda: head.startswith(b"\x00\x01\x00\x00"),
        ".woff": lambda: head.startswith(b"wOFF"),
        ".woff2": lambda: head.startswith(b"wOF2"),
        ".mesh": lambda: head.startswith(b"version "),
        ".rbxm": lambda: head.startswith(b"<roblox!"),
        ".rbxmx": lambda: stripped.startswith((b"<roblox", b"<?xml")) and b"<roblox" in head,
        ".xml": lambda: stripped.startswith((b"<", b"<?xml")),
        ".svg": lambda: stripped.startswith((b"<svg", b"<?xml")),
        ".mp4": lambda: b"ftyp" in head[4:12],
        ".zip": lambda: head.startswith(b"PK\x03\x04"),
    }
    suffix = extension.lower()
    if suffix in checks and not checks[suffix]():
        raise ValueError("extension and file magic differ: " + suffix)
    if suffix == ".json" or stripped.startswith((b"{", b"[")):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeError) as error:
            raise ValueError("malformed JSON asset") from error
        if isinstance(value, dict) and "errors" in value:
            raise ValueError("API error JSON is not a successful asset")
        return "json-checked-not-schema-validated"
    return "magic-checked-not-full-decoder" if suffix in checks else "unclassified"


def content_dependencies(path):
    """Re-read explicit dependencies; do not trust a manifest that omitted them."""
    if path.stat().st_size > 32 * 1024 * 1024:
        return [], "dependency scan limited to 32 MiB"
    with path.open("rb") as stream:
        head = stream.read(32).lstrip()
    if head.startswith(b"<roblox!"):
        helper = Path(__file__).with_name("rbx_binary_dependencies.py")
        spec = importlib.util.spec_from_file_location("verification_binary_reader", helper)
        reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reader)
        return reader.dependencies(path)
    if not head.startswith((b"{", b"[", b"<", b"\xef\xbb\xbf")):
        return [], None
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeError:
        return [], "non-UTF8 text dependency scan skipped"
    found = set()
    if text.lstrip().startswith(("{", "[")):
        try:
            stack = [json.loads(text)]
        except ValueError:
            return [], "invalid JSON dependency scan"
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                for name, value in item.items():
                    if str(name).lower().replace("_", "") in {"assetid", "imageid", "textureid", "meshid", "soundid", "animationid"} and isinstance(value, (str, int)) and str(value).isdigit():
                        found.add("rbxassetid://" + str(value))
                    stack.append(value)
            elif isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, str):
                found.update(m.group(0).rstrip(",);]") for m in URI_RE.finditer(item))
    else:
        found.update(m.group(0).rstrip(",);]") for m in URI_RE.finditer(text))
    return sorted(found), None


def verify(root, manifest, place, universe, inventory_path):
    root = root.resolve()
    inventory = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
    if inventory.get("placeId") != place or inventory.get("universeId") != universe:
        raise ValueError("Actual inventory identity mismatch")
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    summary = data["summary"]
    if summary.get("placeId") != place or summary.get("universeId") != universe:
        raise ValueError("Manifest identity mismatch")
    binding = json.loads((root / "inventory-binding.json").read_text(encoding="utf-8"))
    if binding.get("placeId") != place or binding.get("universeId") != universe or binding.get("inventorySha256") != digest(inventory_path):
        raise ValueError("Actual inventory SHA256/identity differs from output binding")
    errors, checked, missing, content_warnings, actual_dependencies = [], {}, [], [], {}
    records, rejected = data["assets"], data.get("rejected", [])
    by_key = {}
    for record in records:
        key = record.get("key")
        if not isinstance(key, str) or key in by_key:
            errors.append({"key": key, "error": "missing/duplicate request key"})
        by_key[key] = record
        if record.get("status") != "success":
            missing.append({"key": key, "status": record.get("status"), "httpStatus": record.get("http_status")})
            continue
        try:
            value = record["file"]
            rel = PurePosixPath(value)
            if not value or rel.is_absolute() or "\\" in value or ":" in value or any(x in {".", ".."} for x in value.split("/")):
                raise ValueError("unsafe relative path")
            path = root.joinpath(*rel.parts)
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("file escapes download root")
            if not path.is_file() or path.stat().st_size != record["bytes"]:
                raise ValueError("missing file or byte count mismatch")
            actual = digest(path)
            if actual != record["sha256"]:
                raise ValueError("SHA256 mismatch")
            content_status = check_content(path, record.get("extension", path.suffix))
            if content_status == "unclassified":
                content_warnings.append({"key": key, "file": value, "note": "format unclassified; bytes preserved"})
            discovered, scan_note = content_dependencies(path)
            actual_dependencies[key] = discovered
            if scan_note:
                content_warnings.append({"key": key, "file": value, "note": scan_note})
            omitted = set(discovered) - set(record.get("dependencies", []))
            if omitted:
                errors.append({"key": key, "error": "actual file dependencies omitted from manifest", "dependencies": sorted(omitted)})
            checked[value] = {"file": value, "bytes": path.stat().st_size, "sha256": actual,
                              "extension": record.get("extension", path.suffix), "contentStatus": content_status}
        except (KeyError, TypeError, OSError, ValueError) as error:
            errors.append({"key": key, "error": str(error)})
    actual_counts = dict(collections.Counter(r.get("status") for r in records))
    comparisons = {
        "inventory_assets": len(inventory.get("assets", [])),
        "unique_requests_with_dependencies": len(records),
        "statuses": actual_counts,
        "unique_saved_files": len({r.get("sha256") for r in records if r.get("status") == "success"}),
        "unique_saved_bytes": sum({r.get("sha256"): r.get("bytes", 0) for r in records if r.get("status") == "success"}.values()),
        "rejected_references": len(rejected),
    }
    for field, actual in comparisons.items():
        if (field in {"inventory_assets", "unique_requests_with_dependencies"} or field in summary) and summary.get(field) != actual:
            errors.append({"field": field, "error": "summary differs from reconstructed records/inventory", "expected": actual})
    reachable = set()
    def require_reference(uri, asset_id=None, parent=None):
        key = key_for(uri, asset_id)
        if key is None:
            if not any(r.get("uri") == uri and (parent is None or r.get("parent") == parent) for r in rejected):
                errors.append({"uri": uri, "parent": parent, "error": "unsupported reference has no rejection record"})
        elif key not in by_key:
            errors.append({"key": key, "parent": parent, "error": "referenced inventory/dependency has no outcome record"})
        else:
            reachable.add(key)
    for asset in inventory.get("assets", []):
        require_reference(asset.get("uri", ""), asset.get("id"))
    pending, visited = list(reachable), set()
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        record = by_key[key]
        for uri in set(record.get("dependencies", [])) | set(actual_dependencies.get(key, [])):
            require_reference(uri, parent=key)
        pending.extend(reachable - visited)
    for key in by_key.keys() - reachable:
        errors.append({"key": key, "error": "outcome is not reachable from this inventory's references/dependencies"})
    return {"schemaVersion": 2, "placeId": place, "universeId": universe,
            "manifestSha256": digest(manifest), "inventorySha256": digest(inventory_path),
            "statuses": actual_counts, "integrityPassed": not errors,
            "allRequestsSucceeded": not errors and not missing and not rejected,
            "verifiedFiles": list(checked.values()), "missingRequests": missing,
            "rejectedReferences": rejected, "errors": errors, "contentWarnings": content_warnings,
            "referenceClosureChecked": True,
            "scope": "Actual inventory binding, declared-reference closure, content/error-body checks and hashes; no claim of full media decoding, Studio rendering or unreplicated content"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--place-id", type=int, required=True)
    parser.add_argument("--universe-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-all-success", action="store_true")
    args = parser.parse_args()
    report = verify(args.root, args.manifest, args.place_id, args.universe_id, args.inventory)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
    print(json.dumps({k: v for k, v in report.items() if k not in {"verifiedFiles", "missingRequests", "rejectedReferences", "contentWarnings"}}, ensure_ascii=False))
    raise SystemExit(0 if report["integrityPassed"] and (not args.require_all_success or report["allRequestsSucceeded"]) else 1)


if __name__ == "__main__":
    main()
