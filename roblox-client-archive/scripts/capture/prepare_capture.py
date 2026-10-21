#!/usr/bin/env python3
"""Prepare a local, hash-pinned exporter and client scripts; never execute them.

This adapter matches the historical USSI source layout. Unknown upstream layouts
fail before writing. It does not download Xeno, exporters, modules, or API dumps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


MODULES = ("StreamBuffer.luau", "UniversalMethodFinder.luau", "Base64.luau", "llz4.luau")
LICENSES = ("USSI-LICENSE.txt", "SomeHub-LICENSE.txt", "Base64-LICENSE.txt", "llz4-LICENSE.txt")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def relative(value):
    if not isinstance(value, str) or not value or "REPLACE_" in value or "\\" in value or ":" in value:
        raise ValueError("Expected a nonempty workspace-relative slash path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(ord(c) < 32 for c in value) or any(p in {".", ".."} for p in value.split("/")):
        raise ValueError("Unsafe workspace-relative path")
    return value


def lua_value(value):
    if isinstance(value, dict):
        return "{" + ",".join("[" + json.dumps(k, ensure_ascii=False) + "]=" + lua_value(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "{" + ",".join(lua_value(v) for v in value) + "}"
    return json.dumps(value, ensure_ascii=False)


def pinned(entry, config_dir):
    expected = str(entry["sha256"] or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Bind every input to an actual SHA256 first")
    if not isinstance(entry["path"], str) or not entry["path"]:
        raise ValueError("Bind every local input path")
    path = Path(entry["path"])
    if not path.is_absolute():
        path = config_dir / path
    if path.is_symlink() or not path.is_file():
        raise ValueError("Input is missing or a symlink: " + str(path))
    data = path.read_bytes()
    if digest(data) != expected:
        raise ValueError("Input SHA256 mismatch: " + str(path))
    return data


def patch_exporter(source, tools):
    """Exact anchors are intentional: upstream drift requires a reviewed adapter."""
    def swap(old, new, count=1):
        nonlocal source
        if source.count(old) != count:
            raise ValueError("Exporter layout changed at anchor: " + old[:70])
        source = source.replace(old, new)
    swap('game:HttpGet("https://raw.githubusercontent.com/luau/SomeHub/main/" .. filename .. ".luau", true)',
         'readfile(' + json.dumps(tools + "/", ensure_ascii=False) + ' .. filename .. ".luau")', 2)
    swap('local USSI_FOLDER = "ussi_cache/"', 'local USSI_FOLDER = ' + json.dumps(tools + "/ussi_cache/"))
    swap('\t\tldecompile = function()\n\t\t\treturn "-- Decompiling is disabled"\n\t\tend',
         '\t\tldecompile = function(script)\n\t\t\tlocal ok, source = pcall(index, script, "Source")\n\t\t\tif ok and type(source) == "string" and #source > 0 and not string_find(source, "Unable to get property") then return source end\n\t\t\treturn "-- Remote decompilation is disabled; accessible bytecode follows above."\n\t\tend')
    swap('\t\tfor i, fetcher in APIDUMP_FETCHERS do\n\t\t\tlocal o, r = pcall(fetcher)',
         '\t\tfor i, fetcher in APIDUMP_FETCHERS do\n\t\t\tif i ~= 1 then continue end\n\t\t\tlocal o, r = pcall(fetcher)')
    swap('local API_Dump_Decoded = API_Dump',
         'assert(API_Dump, "Pinned API cache missing or version mismatch")\n\t\tlocal API_Dump_Decoded = API_Dump')
    swap('return game:HttpGet("https://assetdelivery.roproxy.com/v1/asset/?" .. asset)',
         'error("LinkedSource network fetch disabled for local archive")')
    swap('game:HttpGet(\n\t\t\t\t\t\t"https://raw.githubusercontent.com/daily3014/rbx-algorithms/refs/heads/main/src/Encoding/Base64.luau",\n\t\t\t\t\t\ttrue\n\t\t\t\t\t)',
         'readfile(' + json.dumps(tools + "/Base64.luau") + ')')
    swap('game:HttpGet("https://raw.githubusercontent.com/RiskoZS/llz4/refs/heads/main/llz4.luau", true)',
         'readfile(' + json.dumps(tools + "/llz4.luau") + ')')
    swap('unknownTag, class, propClass = class, "Folder", "Instance"',
         'local originalClass = class\n\t\t\t\t\tlocal pathOk, fullPath = pcall(instance.GetFullName, instance)\n\t\t\t\t\ttable.insert(GLOBAL_ENV.CLIENT_ARCHIVE_REMAPS, {ClassName=originalClass, Name=name, Path=pathOk and fullPath or name, Action="Unknown class saved as Folder; accessible children retained"})\n\t\t\t\t\tclass, override, propClass = "Folder", replaceClassName(instance, name, originalClass), "Instance"')
    swap('local name = virtual and override.Properties.Name or instance.Name',
         'local name = virtual and override.Properties.Name or instance.Name\n\t\t\tif class == "" then table.insert(GLOBAL_ENV.CLIENT_ARCHIVE_REMAPS, {ClassName="", Name=name, Action="Empty class saved as Folder"}) end')
    swap('local GLOBAL_ENV = getgenv and getgenv() or _G or shared',
         'local GLOBAL_ENV = getgenv and getgenv() or _G or shared\nGLOBAL_ENV.CLIENT_ARCHIVE_REMAPS = {}')
    return '-- Local archival adapter. Retain all accompanying upstream licenses.\n' + source


def prepare(config, config_dir, check_only=False):
    place, universe = config["placeId"], config["universeId"]
    if type(place) is not int or type(universe) is not int or min(place, universe) <= 0:
        raise ValueError("Bind positive integer PlaceId and UniverseId")
    if not isinstance(config["runId"], str) or config["runId"].startswith("REPLACE_") or not re.fullmatch(r"[A-Za-z0-9_-]+", config["runId"]):
        raise ValueError("runId must use letters, digits, underscore, or hyphen")
    tools = relative(config["toolsDirectory"])
    output = relative(config["captureDirectory"])
    if tools == output or tools.startswith(output + "/") or output.startswith(tools + "/"):
        raise ValueError("Tools and capture directories must be separate")
    if not isinstance(config["xenoWorkspace"], str) or not config["xenoWorkspace"]:
        raise ValueError("Bind an existing absolute Xeno workspace")
    workspace = Path(config["xenoWorkspace"]).expanduser()
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError("Bind an existing absolute Xeno workspace")
    workspace = workspace.resolve()
    target = (workspace / tools).resolve()
    if not target.is_relative_to(workspace) or target.exists():
        raise ValueError("Tools target exists or escapes workspace; use a new run directory")
    if (workspace / output).exists():
        raise ValueError("Capture target already exists; preserve it and choose a new run")
    inputs = config["inputs"]
    raw = pinned(inputs["exporter"], config_dir)
    dump_raw = pinned(inputs["apiDump"], config_dir)
    payloads = {name: pinned(inputs[name], config_dir) for name in MODULES + LICENSES}
    dump = json.loads(dump_raw)
    classes = dump.get("Classes")
    if not classes or not any("Default" in m for c in classes for m in c.get("Members", []) if m.get("MemberType") == "Property"):
        raise ValueError("Full API dump with property defaults required")
    version = config["clientFullVersion"]
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", version):
        raise ValueError("Bind the running Player's full four-part version")
    patched = patch_exporter(raw.decode("utf-8-sig").replace("\r\n", "\n"), tools)
    payloads.update({"saveinstance-original.luau": raw, "saveinstance-offline.luau": patched.encode("utf-8"),
                     "ussi_cache/API_DUMP.json": json.dumps({version: classes}, ensure_ascii=False).encode("utf-8")})
    runtime = {"placeId": place, "universeId": universe, "outputDirectory": output, "toolsDirectory": tools}
    terrain = config.get("terrain")
    if terrain and terrain.get("enabled"):
        if terrain["resolution"] != 4:
            raise ValueError("This adapter supports Roblox terrain resolution 4 only")
        relative(terrain["captureName"])
        if "/" in terrain["captureName"]:
            raise ValueError("Terrain captureName must be one directory name")
        low, high, chunk = terrain["min"], terrain["maxExclusive"], terrain["chunkStuds"]
        if not all(isinstance(v, list) and len(v) == 3 and all(type(x) is int and x % 4 == 0 for x in v) for v in (low, high, chunk)):
            raise ValueError("Terrain vectors must contain three integers aligned to resolution 4")
        if not all(chunk[i] > 0 and high[i] > low[i] and (high[i] - low[i]) % chunk[i] == 0 for i in range(3)):
            raise ValueError("Terrain explicit bounds must align with positive chunk sizes")
        if (chunk[0] // 4) * (chunk[1] // 4) * (chunk[2] // 4) > 4194304:
            raise ValueError("Terrain chunk exceeds this adapter's 4,194,304 voxel limit")
        runtime["terrain"] = {k: terrain[k] for k in ("captureName", "min", "maxExclusive", "chunkStuds", "resolution")}
    lua = "local CONFIG = " + lua_value(runtime) + "\n"
    for name in ("diagnostic.luau", "inventory.luau", "run_export.luau", "terrain_probe.luau", "terrain_capture.luau"):
        source = Path(__file__).with_name(name).read_text(encoding="utf-8")
        if source.count("-- CAPTURE_CONFIG") != 1:
            raise ValueError("Template marker mismatch: " + name)
        payloads[name] = source.replace("-- CAPTURE_CONFIG", lua).encode("utf-8")
    report = {"schemaVersion": 1, "placeId": place, "universeId": universe, "runId": config["runId"],
              "clientFullVersion": version, "inputExporterSha256": digest(raw), "inputApiDumpSha256": digest(dump_raw),
              "mode": "prepared-only-not-executed", "captureDirectory": output,
              "files": [{"path": k, "bytes": len(v), "sha256": digest(v)} for k, v in sorted(payloads.items())]}
    if check_only:
        return report
    target.mkdir(parents=True)
    for name, data in payloads.items():
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("xb") as handle:
            handle.write(data)
    with (target / "preparation-manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true", help="Validate inputs and adapter; write nothing")
    args = parser.parse_args()
    report = prepare(json.loads(args.config.read_text(encoding="utf-8-sig")), args.config.resolve().parent, args.check_only)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
