#!/usr/bin/env python3
"""Archive referenced Roblox assets through unauthenticated official endpoints.

Adapted from the historical client archive downloader; all target bindings are CLI inputs.
Only inventory references and explicit dependencies in JSON/XML or binary model string properties are followed.
No cookies, credentials, executor API, process memory, or unrelated cache is read.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import collections
import datetime as dt
import email.utils
import gzip
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


URI_RE = re.compile(r'''(?:rbx(?:asset(?:id)?|thumb)://[^\s<>"']+|https?://[^\s<>"']+)''', re.I)
ASSET_NUMBER_FIELDS = {"assetid", "imageid", "textureid", "meshid", "soundid", "animationid"}
_binary_helper = Path(__file__).resolve().parent / "rbx_binary_dependencies.py"
BINARY_DEPENDENCIES = None
if _binary_helper.is_file():
    _binary_spec = importlib.util.spec_from_file_location("archive_binary_dependencies", _binary_helper)
    _binary_module = importlib.util.module_from_spec(_binary_spec)
    _binary_spec.loader.exec_module(_binary_module)
    BINARY_DEPENDENCIES = _binary_module.dependencies


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def retry_after_seconds(value: str) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            moment = email.utils.parsedate_to_datetime(value)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=dt.timezone.utc)
            return max(0.0, (moment - dt.datetime.now(dt.timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0.0


def paced_wait(seconds: float):
    deadline = time.monotonic() + seconds
    while (remaining := deadline - time.monotonic()) > 0:
        time.sleep(min(10, remaining))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def official_url(url: str) -> bool:
    try:
        p = urllib.parse.urlsplit(url)
        host = (p.hostname or "").lower()
        return (p.scheme == "https" and p.username is None and p.password is None
                and p.port in {None, 443}
                and any(host == x or host.endswith("." + x) for x in ("roblox.com", "rbxcdn.com")))
    except ValueError:
        return False


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not official_url(newurl):
            raise ValueError("Redirect outside Roblox/CDN boundary")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def canonical(uri: str, asset_id=None):
    uri = str(uri or "").strip().replace("&amp;", "&")
    # A thumbnail's id may identify a user or outfit; never treat it as an asset id.
    if uri.lower().startswith("rbxthumb://"):
        query = {key.lower(): values for key, values in urllib.parse.parse_qs(uri[len("rbxthumb://"):]).items()}
        kind = query.get("type", [""])[0].lower()
        identifier = query.get("id", [""])[0]
        routes = {
            "asset": ("assets", "assetIds"),
            "avatarheadshot": ("users/avatar-headshot", "userIds"),
            "avatarbust": ("users/avatar-bust", "userIds"),
            "avatar": ("users/avatar", "userIds"),
            "gamepass": ("game-passes", "gamePassIds"),
        }
        if kind not in routes or not identifier.isdigit() or int(identifier) <= 0:
            return None
        width, height = query.get("w", ["420"])[0], query.get("h", ["420"])[0]
        if not width.isdigit() or not height.isdigit() or int(width) <= 0 or int(height) <= 0:
            return None
        size = str(int(width)) + "x" + str(int(height))
        route, id_parameter = routes[kind]
        parameters = urllib.parse.urlencode({id_parameter: str(int(identifier)), "size": size,
                                            "format": "Png", "isCircular": "false"})
        return "thumbnail:" + kind + ":" + str(int(identifier)) + ":" + size, "https://thumbnails.roblox.com/v1/" + route + "?" + parameters, None
    if asset_id is not None and str(asset_id).isdigit() and int(asset_id) > 0:
        aid = str(int(asset_id))
        return "id:" + aid, "https://assetdelivery.roblox.com/v1/asset/?id=" + aid, aid
    if uri.lower().startswith("rbxassetid://"):
        match = re.match(r"rbxassetid://(\d+)", uri, re.I)
        if match:
            if int(match.group(1)) <= 0:
                return None
            return canonical(uri, match.group(1))
    if uri.lower().startswith("rbxasset://"):
        rel = urllib.parse.unquote(uri[len("rbxasset://"):]).replace("\\", "/")
        return "builtin:" + rel.lower(), "rbxasset://" + rel, None
    if official_url(uri):
        p = urllib.parse.urlsplit(uri)
        query = {key.lower(): values for key, values in urllib.parse.parse_qs(p.query).items()}
        aid = query.get("id", [None])[0]
        if aid and aid.isdigit() and "asset" in p.path.lower():
            return canonical(uri, aid)
        normalized = urllib.parse.urlunsplit(("https", p.netloc.lower(), p.path, p.query, ""))
        return "url:" + hashlib.sha256(normalized.encode()).hexdigest(), normalized, None
    return None


def infer_extension(head: bytes, mime: str = "") -> str:
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    s = head.lstrip()
    if head.startswith(b"\x89PNG\r\n\x1a\n"): return ".png"
    if head.startswith(b"\xff\xd8\xff"): return ".jpg"
    if head.startswith((b"GIF87a", b"GIF89a")): return ".gif"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP": return ".webp"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE": return ".wav"
    if head.startswith(b"OggS"): return ".ogg"
    if head.startswith(b"ID3") or head[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}: return ".mp3"
    if head.startswith(b"OTTO"): return ".otf"
    if head.startswith(b"\x00\x01\x00\x00"): return ".ttf"
    if head.startswith(b"wOFF"): return ".woff"
    if head.startswith(b"wOF2"): return ".woff2"
    if head.startswith(b"version "): return ".mesh"
    if head.startswith(b"<roblox!"): return ".rbxm"
    if s.startswith((b"<roblox", b"<?xml")): return ".rbxmx" if b"<roblox" in head else ".xml"
    if s.startswith((b"{", b"[")): return ".json"
    if s.startswith(b"<svg"): return ".svg"
    if b"ftyp" in head[4:12]: return ".mp4"
    if head.startswith(b"PK\x03\x04"): return ".zip"
    if s.startswith((b"<!DOCTYPE html", b"<html")): return ".html"
    return {"image/png": ".png", "image/jpeg": ".jpg", "application/json": ".json",
            "text/xml": ".xml", "application/xml": ".xml"}.get(mime.split(";")[0].strip(), ".bin")


def validate_content(path, extension, mime=""):
    with path.open("rb") as stream:
        head = stream.read(2048)
    lower = head.lstrip().lower()
    if not head:
        raise ValueError("Empty response is not a successful asset")
    if "text/html" in mime.lower() or lower.startswith((b"<html", b"<!doctype html")):
        raise ValueError("HTML error/login document is not a successful asset")
    detected = infer_extension(head)
    known = {".png", ".jpg", ".gif", ".webp", ".wav", ".ogg", ".mp3", ".otf", ".ttf", ".woff", ".woff2", ".mesh", ".rbxm", ".rbxmx", ".xml", ".json", ".svg", ".mp4", ".zip"}
    aliases = {".jpeg": ".jpg"}
    suffix = aliases.get(extension.lower(), extension.lower())
    if suffix in known and detected != suffix:
        raise ValueError("Declared format and file magic differ: " + suffix + " vs " + detected)
    if detected == ".json":
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeError) as error:
            raise ValueError("Malformed JSON asset") from error
        if isinstance(value, dict) and "errors" in value:
            raise ValueError("API error JSON is not a successful asset")
    return detected


def dependencies(path: Path):
    """Read explicit URI dependencies from text or binary string fields, never execute assets."""
    if path.stat().st_size > 32 * 1024 * 1024:
        return [], "text dependency scan limited to 32 MiB"
    with path.open("rb") as f:
        head = f.read(2048).lstrip()
    if head.startswith(b"<roblox!"):
        if BINARY_DEPENDENCIES is None:
            return [], "binary dependency helper unavailable"
        return BINARY_DEPENDENCIES(path)
    if not head.startswith((b"{", b"[", b"<")):
        return [], None
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeError:
        return [], None
    found = set()
    if head.startswith((b"{", b"[")):
        try:
            j = json.loads(text)
        except ValueError:
            return [], "response looked like JSON but could not be parsed"
        stack = [j]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                for name, val in item.items():
                    if str(name).lower().replace("_", "") in ASSET_NUMBER_FIELDS and isinstance(val, (str, int)) and str(val).isdigit():
                        found.add("rbxassetid://" + str(val))
                    stack.append(val)
            elif isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, str):
                found.update(match.group(0).rstrip(",);]") for match in URI_RE.finditer(item))
    else:
        found.update(match.group(0).rstrip(",);]") for match in URI_RE.finditer(text))
    # Reject unrecognized URLs; all rejected references are recorded separately.
    return sorted(found), None


def discover_content_roots():
    bases = [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Roblox/Versions",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Roblox/Versions"]
    roots = []
    for base in bases:
        if base.is_dir():
            for version in sorted(base.glob("version-*"), key=lambda p: p.stat().st_mtime, reverse=True):
                for rel in ("content", "ExtraContent", "PlatformContent/pc", "PlatformContent/shared"):
                    root = version / rel
                    if root.is_dir(): roots.append(root.resolve())
    return roots


class Downloader:
    def __init__(self, args, inventory):
        self.args, self.inventory = args, inventory
        self.root = args.output.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.tmp = self.root / ".partial"
        self.tmp.mkdir(exist_ok=True)
        if not self.tmp.resolve().is_relative_to(self.root):
            raise ValueError("Partial directory escapes output root")
        self.content_roots = [p.resolve() for p in args.content_root]
        self.records, self.jobs, self.rejected = {}, {}, []
        self.progress = self.root / "download-progress.jsonl"
        if not self.progress.resolve().is_relative_to(self.root):
            raise ValueError("Progress path escapes output root")
        if self.progress.exists():
            for line in self.progress.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                    self.records[r["key"]] = r
                except (ValueError, KeyError): pass
        binding = self.root / "inventory-binding.json"
        if not binding.resolve().is_relative_to(self.root):
            raise ValueError("Binding path escapes output root")
        identity = {"placeId": inventory["placeId"], "universeId": inventory["universeId"], "inventorySha256": sha256(args.inventory)}
        if binding.exists() and json.loads(binding.read_text(encoding="utf-8")) != identity:
            raise RuntimeError("Output belongs to a different inventory; choose a new output directory")
        if not binding.exists():
            if self.progress.exists():
                raise RuntimeError("Existing progress has no inventory binding; use a fresh output directory")
            with binding.open("x", encoding="utf-8") as out: json.dump(identity, out, indent=2)
        self.log = self.progress.open("a", encoding="utf-8")
        self.gate_lock = threading.Lock()
        self.publish_lock = threading.Lock()
        self.next_request = self.pause_until = 0.0
        self.error_stats = collections.Counter()
        for index, asset in enumerate(inventory.get("assets", [])):
            self.add(asset.get("uri", ""), asset.get("id"), index=index)

    def add(self, uri, aid=None, index=None, parent=None):
        normalized = canonical(uri, aid)
        if normalized is None:
            self.rejected.append({"uri": uri, "inventory_index": index, "parent": parent,
                                  "reason": "unsupported scheme or outside Roblox/CDN boundary"})
            return
        key, request_uri, aid = normalized
        job = self.jobs.setdefault(key, {"key": key, "uri": request_uri, "id": aid,
                                        "source_uris": [], "inventory_indices": [], "parents": []})
        if uri not in job["source_uris"]: job["source_uris"].append(uri)
        if index is not None and index not in job["inventory_indices"]: job["inventory_indices"].append(index)
        if parent is not None and parent not in job["parents"]: job["parents"].append(parent)

    def gate(self):
        with self.gate_lock:
            moment = max(time.monotonic(), self.next_request, self.pause_until)
            self.next_request = moment + 1.0 / self.args.requests_per_second
        delay = moment - time.monotonic()
        if delay > 0: paced_wait(delay)

    def handle_builtin(self, job):
        rel = job["uri"][len("rbxasset://"):]
        parts = Path(rel)
        if parts.is_absolute() or ":" in rel or ".." in parts.parts:
            return {"status": "rejected", "error": "unsafe builtin relative path"}
        for content_root in self.content_roots:
            src = (content_root / parts).resolve()
            if src.is_relative_to(content_root) and src.is_file():
                temp = self.tmp / (uuid.uuid4().hex + ".raw")
                shutil.copyfile(src, temp)
                return self.publish(temp, job, suffix=src.suffix or ".bin", local_source=str(src))
        return {"status": "local_missing", "error": "not found in Roblox installation content roots"}

    def publish(self, temp, job, suffix, **extra):
        detected = validate_content(temp, suffix, extra.get("content_type", ""))
        checksum = sha256(temp)
        target = self.root / "objects" / checksum[:2] / (checksum + suffix.lower())
        if not target.resolve().is_relative_to(self.root):
            raise ValueError("Object path escapes output root")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.publish_lock:
            if target.exists():
                if sha256(target) != checksum:
                    raise RuntimeError("existing output failed SHA256; refusing to overwrite")
                temp.unlink(missing_ok=True)
            else:
                # A unique hash name plus exclusive creation protects existing output.
                try:
                    with target.open("xb") as out, temp.open("rb") as inp:
                        shutil.copyfileobj(inp, out, 1024 * 1024)
                except FileExistsError:
                    if sha256(target) != checksum: raise RuntimeError("output collision")
                finally:
                    temp.unlink(missing_ok=True)
        deps, note = dependencies(target)
        return {"status": "success", "file": target.relative_to(self.root).as_posix(),
                "bytes": target.stat().st_size, "sha256": checksum, "extension": suffix,
                "dependencies": deps, "dependency_scan_note": note,
                "detected_extension": detected, "format_status": "unclassified" if detected == ".bin" else "magic-checked-not-full-decoder", **extra}

    def download(self, job):
        old = self.records.get(job["key"])
        if old and old.get("status") == "success":
            existing = (self.root / old.get("file", "")).resolve()
            if existing.is_relative_to(self.root) and existing.is_file() and sha256(existing) == old.get("sha256"):
                try:
                    validate_content(existing, old.get("extension", existing.suffix), old.get("content_type", ""))
                except ValueError as error:
                    return {**old, "status": "invalid_content", "error": str(error), "reused": False}
                return {**old, "reused": True}
        start = time.monotonic()
        base = {"key": job["key"], "id": job["id"], "uri": job["uri"], "finished_utc": now()}
        try:
            if job["key"].startswith("builtin:"):
                return {**base, **self.handle_builtin(job)}
            opener = urllib.request.build_opener(SafeRedirect())
            for attempt in range(1, self.args.attempts + 1):
                temp = self.tmp / (uuid.uuid4().hex + ".raw")
                try:
                    self.gate()
                    request = urllib.request.Request(job["uri"], headers={
                        "User-Agent": "Roblox/WinInet", "Accept": "*/*", "Accept-Encoding": "identity"})
                    with opener.open(request, timeout=self.args.timeout) as response:
                        if not official_url(response.url): raise ValueError("final response outside official domain boundary")
                        mime = response.headers.get("Content-Type", "")
                        total = 0
                        with temp.open("xb") as out:
                            while block := response.read(1024 * 1024):
                                total += len(block)
                                if self.args.max_asset_mib and total > self.args.max_asset_mib * 1024 * 1024:
                                    raise ValueError("asset exceeds configured maximum size")
                                out.write(block)
                        final = urllib.parse.urlsplit(response.url)
                    wire_sha = sha256(temp)
                    with temp.open("rb") as raw: compressed = raw.read(2) == b"\x1f\x8b"
                    if compressed:
                        decoded = self.tmp / (uuid.uuid4().hex + ".decoded")
                        try:
                            with gzip.open(temp, "rb") as inp, decoded.open("xb") as out:
                                expanded = 0
                                while block := inp.read(1024 * 1024):
                                    expanded += len(block)
                                    if self.args.max_asset_mib and expanded > self.args.max_asset_mib * 1024 * 1024:
                                        raise ValueError("decoded asset exceeds configured maximum size")
                                    out.write(block)
                        except Exception:
                            decoded.unlink(missing_ok=True)
                            raise
                        temp.unlink()
                        temp = decoded
                    with temp.open("rb") as inp: head = inp.read(2048)
                    ext = infer_extension(head, mime)
                    if ext == ".html" or "text/html" in mime.lower():
                        raise ValueError("HTML response is not archived as a successful asset")
                    # API error JSON should not be mistaken for the requested asset.
                    if ext == ".json":
                        try:
                            sample = json.loads(temp.read_text(encoding="utf-8"))
                        except (ValueError, UnicodeError): sample = None
                        if isinstance(sample, dict) and "errors" in sample:
                            temp.unlink()
                            return {**base, "status": "api_error", "attempts": attempt,
                                    "error": json.dumps(sample, ensure_ascii=False)[:800]}
                    result = self.publish(temp, job, ext, content_type=mime,
                                          downloaded_bytes=total, response_sha256=wire_sha,
                                          gzip_decoded=compressed,
                                          final_origin_path=urllib.parse.urlunsplit((final.scheme, final.netloc, final.path, "", "")))
                    return {**base, **result, "attempts": attempt, "elapsed_seconds": round(time.monotonic()-start, 3)}
                except urllib.error.HTTPError as error:
                    temp.unlink(missing_ok=True)
                    code = error.code
                    body = error.read(2048).decode("utf-8", "replace")[:500]
                    error.close()
                    retry = min(300.0, retry_after_seconds(error.headers.get("Retry-After", "")))
                    if code == 429 and retry > 0:
                        with self.gate_lock:
                            self.pause_until = max(self.pause_until, time.monotonic() + retry)
                    if code in {429, 500, 502, 503, 504} and attempt < self.args.attempts:
                        delay = max(retry, 2 ** attempt + random.random())
                        if code == 429:
                            with self.gate_lock: self.pause_until = max(self.pause_until, time.monotonic() + delay)
                        paced_wait(delay)
                        continue
                    return {**base, "status": "http_error", "http_status": code,
                            "error": body, "attempts": attempt, "retry_after_seconds": retry}
                except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                    temp.unlink(missing_ok=True)
                    if attempt < self.args.attempts:
                        time.sleep(min(30, 2 ** attempt + random.random()))
                        continue
                    return {**base, "status": "network_error", "error": str(error)[:500], "attempts": attempt}
                finally:
                    temp.unlink(missing_ok=True)
        except Exception as error:
            return {**base, "status": "error", "error": str(error)[:500]}

    def run(self):
        started = now()
        done, scheduled, futures = set(), set(), {}
        last_print = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.args.workers) as executor:
            while True:
                for key, job in list(self.jobs.items()):
                    if key not in scheduled and len(futures) < self.args.workers * 2:
                        futures[executor.submit(self.download, job)] = key
                        scheduled.add(key)
                if not futures: break
                ready, _ = concurrent.futures.wait(futures, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in ready:
                    key = futures.pop(future)
                    r = future.result()
                    self.records[key] = r
                    self.log.write(json.dumps(r, ensure_ascii=False) + "\n")
                    self.log.flush()
                    done.add(key)
                    if r["status"] == "success":
                        for uri in r.get("dependencies", []): self.add(uri, parent=key)
                if time.monotonic() - last_print >= 15 or len(done) == len(self.jobs):
                    stats = collections.Counter(r["status"] for key,r in self.records.items() if key in done)
                    print(json.dumps({"completed": len(done), "discovered": len(self.jobs), "statuses": dict(stats)}, ensure_ascii=False), flush=True)
                    last_print = time.monotonic()
        self.log.close()
        try:
            # Remove only this run's empty managed temporary directory. Never
            # recurse or discard retained partial evidence from an interrupted run.
            self.tmp.rmdir()
        except OSError:
            pass
        records = []
        for key, job in self.jobs.items():
            r = {**self.records[key], **job}
            r["reference_count"] = sum(len(self.inventory["assets"][i].get("references", [])) for i in job["inventory_indices"])
            records.append(r)
        counts = collections.Counter(r["status"] for r in records)
        http_counts = collections.Counter(str(r.get("http_status")) for r in records if r.get("http_status"))
        distinct = {r["sha256"]: r["bytes"] for r in records if r["status"] == "success"}
        summary = {"started_utc": started, "finished_utc": now(), "inventory_assets": len(self.inventory.get("assets", [])),
                   "placeId": self.inventory["placeId"], "universeId": self.inventory["universeId"],
                   "unique_requests_with_dependencies": len(records), "statuses": dict(counts),
                   "http_failures": dict(http_counts), "unique_saved_files": len(distinct),
                   "unique_saved_bytes": sum(distinct.values()), "rejected_references": len(self.rejected),
                   "content_roots": [str(p) for p in self.content_roots],
                   "authentication": "none; no cookies or account credentials",
                   "scope": "inventory references plus explicit JSON/XML and binary model string URI dependencies; official Roblox/CDN only",
                   "limits": {"workers": self.args.workers, "requests_per_second": self.args.requests_per_second,
                              "attempts": self.args.attempts, "maximum_asset_mib": self.args.max_asset_mib,
                              "text_dependency_scan_mib": 32},
                   "inventory_file": str(self.args.inventory.resolve())}
        for name, data in (("download-manifest.json", {"summary": summary, "assets": records, "rejected": self.rejected}),
                           ("download-summary.json", summary),
                           ("download-failures.json", [r for r in records if r["status"] != "success"])):
            path = self.root / name
            if path.exists():
                # Keep the previous reviewable report rather than overwrite it.
                path = self.root / (path.stem + "-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S") + path.suffix)
            with path.open("x", encoding="utf-8") as out: json.dump(data, out, ensure_ascii=False, indent=2)
        print(json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--place-id", type=int, required=True)
    parser.add_argument("--universe-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--content-root", type=Path, action="append", default=[])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--requests-per-second", type=float, default=10)
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--max-asset-mib", type=int, default=0, help="0 means no byte-size limit")
    args = parser.parse_args()
    if args.workers < 1 or not math.isfinite(args.requests_per_second) or args.requests_per_second <= 0 or args.attempts < 1: parser.error("positive finite concurrency/rate/attempts required")
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    if inventory.get("placeId") != args.place_id or inventory.get("universeId") != args.universe_id:
        raise SystemExit("Inventory identity differs from the explicitly bound Place/Universe")
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.max_asset_mib < 0 or args.place_id <= 0 or args.universe_id <= 0:
        parser.error("positive timeout and identities, nonnegative maximum required")
    args.output.mkdir(parents=True, exist_ok=True)
    lock = args.output / ".download.lock"
    try:
        with lock.open("x", encoding="ascii") as out: out.write(str(os.getpid()))
    except FileExistsError:
        raise SystemExit("Download lock already exists; verify the other run has stopped before removing it.")
    try: Downloader(args, inventory).run()
    finally: lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
