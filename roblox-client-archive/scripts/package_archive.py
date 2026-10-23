#!/usr/bin/env python3
"""Package an already reviewed client archive; never collect or execute game code."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from datetime import datetime, timezone
import zipfile
from xml.parsers import expat


MANIFEST = "file-checksums.json"
METADATA = "archive-metadata.json"
LAUNCHER = "启动场景.cmd"
RESERVED = {MANIFEST.casefold(), METADATA.casefold(), LAUNCHER.casefold()}
BLOCKED = {".git", "__pycache__"}
SCENES = ("snapshot/scene.rbxlx", "snapshot/scene.rbxl", "scene.rbxlx", "scene.rbxl")
METADATA_CANDIDATES = ("metadata.json", "snapshot/metadata.json", "archive-summary.json", "inventory.json", "manifest.json")


class ArchiveError(Exception):
    """An input, integrity, or portability check failed."""


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def is_reparse(st):
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def check_path_chain(path):
    """Check lexical ancestors before resolving, so links cannot disappear in resolve()."""
    path = Path(os.path.abspath(path))
    for candidate in (*reversed(path.parents), path):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if is_reparse(info):
            raise ArchiveError(f"Symbolic link/reparse point rejected: {candidate}")
    return path


def is_within(child, parent):
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def external_path(path, source, *, must_exist=False):
    path = check_path_chain(path)
    if is_within(path, source) or is_within(source, path):
        raise ArchiveError("Source and output paths must not contain one another")
    if not path.parent.is_dir():
        raise ArchiveError(f"Output parent must already exist: {path.parent}")
    if must_exist:
        if not path.is_file():
            raise ArchiveError(f"Input ZIP does not exist: {path}")
    elif path.exists():
        raise ArchiveError(f"Refusing to overwrite: {path}")
    return path


def safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or name.startswith("/"):
        raise ArchiveError(f"Unsafe archive-relative path: {name!r}")
    parts = PurePosixPath(name).parts
    if not parts or any(part in (".", "..") for part in parts) or "/".join(parts) != name:
        raise ArchiveError(f"Unsafe archive-relative path: {name!r}")
    for part in parts:
        if re.search(r'[<>:"|?*\x00-\x1f\x7f-\x9f\u2028\u2029]', part) or part.endswith((" ", ".")):
            raise ArchiveError(f"Non-portable Windows filename: {name!r}")
        if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.I):
            raise ArchiveError(f"Reserved Windows filename: {name!r}")
        lower = part.casefold()
        if lower in BLOCKED or lower.endswith((".lock", ".partial", ".tmp")):
            raise ArchiveError(f"Unfinished/local-only item must be reviewed outside staging: {name}")
    return name


def file_digest(path):
    check_path_chain(path)
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or is_reparse(before):
        raise ArchiveError(f"Only regular files are allowed: {path}")
    digest = hashlib.sha256()
    total = 0
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ArchiveError(f"File identity changed while reading: {path}")
        while block := handle.read(1024 * 1024):
            total += len(block)
            digest.update(block)
    after = path.stat(follow_symlinks=False)
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino) or total != before.st_size:
        raise ArchiveError(f"File changed while hashing: {path}")
    return {"bytes": total, "sha256": digest.hexdigest()}


def inventory(source):
    result, seen = {}, set()
    def walk(directory):
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            name = safe_name(path.relative_to(source).as_posix())
            folded = name.casefold()
            if folded in seen:
                raise ArchiveError(f"Case-insensitive path collision: {name}")
            seen.add(folded)
            info = path.lstat()
            if is_reparse(info):
                raise ArchiveError(f"Symbolic link/reparse point rejected: {path}")
            if stat.S_ISDIR(info.st_mode):
                walk(path)
            elif stat.S_ISREG(info.st_mode):
                if name.casefold() in RESERVED:
                    raise ArchiveError(f"Reserved generated name already exists in source: {name}")
                result[name] = file_digest(path)
            else:
                raise ArchiveError(f"Non-regular filesystem object rejected: {path}")
    walk(source)
    return dict(sorted(result.items()))


def inventory_hash(files):
    return sha_bytes(json_bytes(files))


def select_input(files, explicit, candidates, label, suffixes):
    if explicit:
        choices = [safe_name(explicit)]
    else:
        choices = [candidate for candidate in candidates if candidate in files]
    if len(choices) != 1 or choices[0] not in files:
        raise ArchiveError(f"Choose exactly one existing {label} with its relative-path option; candidates: {choices}")
    chosen = choices[0]
    if Path(chosen).suffix.lower() not in suffixes:
        raise ArchiveError(f"Unexpected {label} extension: {chosen}")
    return chosen


def validate_required(source, files, scene_relative_path=None, metadata_relative_path=None, native_scene_relative_path=None):
    if not any(name.casefold() in ("readme.md", "readme.txt") for name in files):
        raise ArchiveError("Source needs a root README.md or README.txt explaining scope and limitations")
    scene = select_input(files, scene_relative_path, SCENES, "scene", {".rbxl", ".rbxlx"})
    evidence = select_input(files, metadata_relative_path, METADATA_CANDIDATES, "metadata JSON", {".json"})
    try:
        value = json.loads((source / evidence).read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise ArchiveError(f"Invalid metadata JSON: {evidence}: {exc}") from exc
    if not isinstance(value, (dict, list)) or not value:
        raise ArchiveError("Metadata JSON must be a nonempty object or array from the collection step")
    native = None
    if native_scene_relative_path:
        native = select_input(files, native_scene_relative_path, (), "native scene", {".rbxl"})
    elif scene.lower().endswith(".rbxl"):
        native = scene
    return scene, evidence, native


def validate_launcher_scene(source, files, relative, *, explicit):
    """Keep the legacy native alias; explicit targets also need matching file content."""
    scene = select_input(files, relative, (), "launcher scene", {".rbxl", ".rbxlx"})
    # The CMD bootstrap finds its static marker in the file. Reject a second one
    # in a filename rather than letting it alter the extracted PowerShell body.
    if "# POWERSHELL" in scene:
        raise ArchiveError("Launcher filename contains the reserved bootstrap marker")
    if not explicit:
        if Path(scene).suffix.lower() != ".rbxl":
            raise ArchiveError("An XML launcher scene requires --launcher-scene-relative-path explicitly")
        return scene
    path = source / scene
    check_path_chain(path)
    if Path(scene).suffix.lower() == ".rbxl":
        with path.open("rb") as handle:
            if handle.read(14) != b"<roblox!\x89\xff\r\n\x1a\n":
                raise ArchiveError(f"Launcher .rbxl does not have the native Roblox signature: {scene}")
        return scene
    parser = expat.ParserCreate()
    root_seen = False
    def start_element(name, attributes):
        nonlocal root_seen
        if not root_seen:
            root_seen = True
            if name != "roblox" or attributes.get("version") != "4":
                raise ArchiveError("Launcher XML must have a roblox root with version 4")
    def reject_dtd(*_args):
        raise ArchiveError("Launcher XML declarations for DTD/entities are not accepted")
    parser.StartElementHandler = start_element
    parser.StartDoctypeDeclHandler = reject_dtd
    parser.EntityDeclHandler = reject_dtd
    parser.ExternalEntityRefHandler = reject_dtd
    try:
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                parser.Parse(block, False)
        parser.Parse(b"", True)
    except expat.ExpatError as exc:
        raise ArchiveError(f"Invalid launcher .rbxlx XML: {scene}: {exc}") from exc
    if not root_seen:
        raise ArchiveError("Launcher XML has no Roblox root")
    return scene


def launcher_bytes(scene):
    # The payload is static except for a quoted, validated relative filename.
    scene = safe_name(scene).replace("'", "''")
    if "# POWERSHELL" in scene:
        raise ArchiveError("Launcher filename contains the reserved bootstrap marker")
    command = r'''@echo off
setlocal
set "ARCHIVE_ROOT=%~dp0"
set "ARCHIVE_LAUNCHER=%~f0"
set "ARCHIVE_CHECK_ONLY="
if /I "%~1"=="-CheckOnly" set "ARCHIVE_CHECK_ONLY=1"
if /I "%~1"=="/CheckOnly" set "ARCHIVE_CHECK_ONLY=1"
powershell.exe -NoLogo -NoProfile -Command "$p=[IO.File]::ReadAllText($env:ARCHIVE_LAUNCHER);$m='# POWERSHELL'; & ([ScriptBlock]::Create($p.Substring($p.LastIndexOf($m)+$m.Length)))"
exit /b %errorlevel%
# POWERSHELL
$ErrorActionPreference='Stop'
try {
  $root=[IO.Path]::GetFullPath($env:ARCHIVE_ROOT)
  function ArchivePath([string]$relative) {
    if ([IO.Path]::IsPathRooted($relative) -or (($relative -split '[\\/]') -contains '..') -or $relative.Contains(':')) { throw 'Unsafe package path' }
    $path=[IO.Path]::GetFullPath((Join-Path $root $relative))
    if (-not $path.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)) { throw 'Path outside package' }
    $item=Get-Item -LiteralPath $path -Force
    while ($null -ne $item -and $item.FullName.Length -ge $root.TrimEnd('\').Length) {
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Package reparse point rejected' }
      if ($item -is [IO.FileInfo]) { $item=$item.Directory } else { $item=$item.Parent }
    }
    return $path
  }
  $manifest=Get-Content -LiteralPath (ArchivePath 'file-checksums.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  foreach ($entry in $manifest.files) {
    $path=ArchivePath $entry.path
    $stream=[IO.File]::OpenRead($path)
    $sha=[Security.Cryptography.SHA256]::Create()
    try { $size=$stream.Length; $hash=([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $sha.Dispose() }
    if ($size -ne $entry.bytes -or $hash -ne $entry.sha256) { throw ('Package checksum failed: '+$entry.path) }
  }
  $scene=ArchivePath '__SCENE__'
  if ($env:STUDIO_EXE) {
    if (-not [IO.Path]::IsPathRooted($env:STUDIO_EXE)) { throw 'STUDIO_EXE must be an absolute executable path' }
    $studioItem=Get-Item -LiteralPath $env:STUDIO_EXE
    if ($studioItem.PSIsContainer) { throw 'STUDIO_EXE must name a file' }
    $studio=$studioItem.FullName
    if ([IO.Path]::GetExtension($studio) -ne '.exe') { throw 'STUDIO_EXE must name an .exe file' }
  } else {
    $candidates=@()
    foreach ($base in @($env:LOCALAPPDATA,$env:ProgramFiles,${env:ProgramFiles(x86)})) {
      if (-not $base) { continue }
      $versions=Join-Path $base 'Roblox\Versions'
      if (Test-Path -LiteralPath $versions -PathType Container) {
        foreach ($directory in Get-ChildItem -LiteralPath $versions -Directory) {
          $candidate=Join-Path $directory.FullName 'RobloxStudioBeta.exe'
          if (Test-Path -LiteralPath $candidate -PathType Leaf) { $candidates += $candidate }
        }
      }
    }
    $candidates=@($candidates | Sort-Object -Unique)
    if ($candidates.Count -ne 1) { throw ('Found '+$candidates.Count+' Studio candidates; set STUDIO_EXE explicitly. '+($candidates -join '; ')) }
    $studio=$candidates[0]
  }
  Write-Output ('Validated package; scene: '+$scene)
  Write-Output ('Studio: '+$studio)
  if ($env:ARCHIVE_CHECK_ONLY -eq '1') { Write-Output 'CheckOnly: no Studio process started'; exit 0 }
  Start-Process -FilePath $studio -ArgumentList @('-task','EditFile','-localPlaceFile',('"'+$scene+'"')) | Out-Null
  exit 0
} catch { Write-Error $_; exit 1 }
'''
    return command.replace("__SCENE__", scene).replace("\n", "\r\n").encode("utf-8")


def verify_archive(source, archive, before, expected_selection=None, expected_launcher_scene=None):
    """Independently reread every ZIP entry and compare it to source and manifest."""
    with zipfile.ZipFile(archive, "r") as zipped:
        info = zipped.infolist()
        names, folded = [], set()
        for item in info:
            safe_name(item.filename)
            if item.is_dir() or item.filename.casefold() in folded:
                raise ArchiveError("Duplicate, case-colliding, or directory ZIP entry")
            if stat.S_ISLNK(item.external_attr >> 16) or item.external_attr & 0x400 or item.flag_bits & 1:
                raise ArchiveError("Symlink/encrypted ZIP entry rejected")
            folded.add(item.filename.casefold())
            names.append(item.filename)
        bad_crc = zipped.testzip()
        if bad_crc:
            raise ArchiveError(f"ZIP CRC failed: {bad_crc}")
        try:
            manifest = json.loads(zipped.read(MANIFEST))
            metadata = json.loads(zipped.read(METADATA))
        except (KeyError, ValueError, UnicodeError) as exc:
            raise ArchiveError(f"Missing/invalid generated JSON: {exc}") from exc
        if manifest.get("schemaVersion") != 1 or manifest.get("algorithm") != "sha256" or manifest.get("selfExcluded") != [MANIFEST]:
            raise ArchiveError("Unsupported checksum manifest or invalid self-exclusion")
        if metadata.get("schemaVersion") != 1 or metadata.get("sourceInventorySha256") != inventory_hash(before):
            raise ArchiveError("ZIP does not match the original source inventory")
        selection = (metadata.get("sceneRelativePath"), metadata.get("metadataRelativePath"), metadata.get("nativeSceneRelativePath"))
        actual_selection = validate_required(source, before, *selection[:2], selection[2])
        if actual_selection != selection or (expected_selection and selection != expected_selection):
            raise ArchiveError("Scene/metadata selection mismatch")
        launcher = metadata.get("launcherCreated")
        if not isinstance(launcher, bool):
            raise ArchiveError("Invalid launcher metadata")
        if "launcherSceneRelativePath" in metadata:
            launcher_scene = metadata["launcherSceneRelativePath"]
            launcher_explicit = metadata.get("launcherSceneExplicit")
            if not isinstance(launcher_explicit, bool):
                raise ArchiveError("Invalid explicit launcher selection metadata")
            if launcher:
                if not isinstance(launcher_scene, str) or not launcher_scene:
                    raise ArchiveError("Invalid launcher scene metadata")
                validate_launcher_scene(source, before, launcher_scene, explicit=launcher_explicit)
                if not launcher_explicit and launcher_scene != selection[2]:
                    raise ArchiveError("Native launcher selection mismatch")
            elif launcher_scene is not None or launcher_explicit:
                raise ArchiveError("Unexpected scene selection for a package without a launcher")
        else:
            # Schema-1 archives produced before explicit XML launchers remain
            # verifiable with their original three-field selection and payload.
            if "launcherSceneExplicit" in metadata or (launcher and not selection[2]):
                raise ArchiveError("Invalid legacy launcher metadata")
            launcher_scene = selection[2] if launcher else None
        if expected_launcher_scene is not None and launcher_scene != expected_launcher_scene:
            raise ArchiveError("Launcher scene selection mismatch")
        expected = dict(before)
        expected[METADATA] = {"bytes": len(zipped.read(METADATA)), "sha256": sha_bytes(zipped.read(METADATA))}
        if launcher:
            payload = launcher_bytes(launcher_scene)
            expected[LAUNCHER] = {"bytes": len(payload), "sha256": sha_bytes(payload)}
        rows = manifest.get("files")
        if not isinstance(rows, list) or len(rows) != len(expected):
            raise ArchiveError("Manifest entry count mismatch")
        declared = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
                raise ArchiveError("Invalid manifest record")
            name = safe_name(row["path"])
            if name in declared:
                raise ArchiveError("Duplicate manifest record")
            declared[name] = {"bytes": row["bytes"], "sha256": row["sha256"]}
        if declared != expected:
            raise ArchiveError("Manifest hashes/sizes differ from source or generated payload")
        if set(names) != set(expected) | {MANIFEST}:
            raise ArchiveError("ZIP entry set mismatch")
        for name, record in expected.items():
            entry = zipped.getinfo(name)
            if entry.file_size != record["bytes"]:
                raise ArchiveError(f"ZIP entry size mismatch: {name}")
            digest, size = hashlib.sha256(), 0
            with zipped.open(name) as stream:
                while block := stream.read(1024 * 1024):
                    size += len(block)
                    digest.update(block)
            if size != record["bytes"] or digest.hexdigest() != record["sha256"]:
                raise ArchiveError(f"ZIP entry SHA-256 mismatch: {name}")
    return {"entryCount": len(names), "sourceFileCount": len(before), "crc": "passed", "entrySet": "passed", "allEntrySizesAndSha256": "passed", "selection": list(selection), "launcherCreated": launcher, "launcherSceneRelativePath": launcher_scene}


def package_archive(source, output=None, *, verify_existing=None, verification_output=None,
                    scene_relative_path=None, metadata_relative_path=None,
                    native_scene_relative_path=None, create_launcher=False,
                    launcher_scene_relative_path=None):
    source = check_path_chain(source)
    if not source.is_dir():
        raise ArchiveError("Source must be an existing reviewed staging directory")
    if launcher_scene_relative_path is not None and not create_launcher and not verify_existing:
        raise ArchiveError("--launcher-scene-relative-path requires --create-launcher in creation mode")
    if (launcher_scene_relative_path is not None and native_scene_relative_path is not None
            and launcher_scene_relative_path != native_scene_relative_path):
        raise ArchiveError("Explicit launcher and native scene options must select the same file; omit the native alias to select XML")
    if verify_existing:
        if output or create_launcher:
            raise ArchiveError("Verification mode accepts neither --output nor --create-launcher")
        archive = external_path(verify_existing, source, must_exist=True)
    else:
        if not output:
            raise ArchiveError("Creation mode requires --output")
        archive = external_path(output, source)
        if archive.suffix.lower() != ".zip":
            raise ArchiveError("Output must have the .zip extension")
    report_path = external_path(verification_output or (str(archive) + (".reverification.json" if verify_existing else ".verification.json")), source)
    if report_path == archive:
        raise ArchiveError("Verification report and ZIP must be different files")
    before = inventory(source)
    selection = validate_required(source, before, scene_relative_path, metadata_relative_path, native_scene_relative_path)
    if create_launcher and not selection[2] and launcher_scene_relative_path is None:
        raise ArchiveError("--create-launcher requires a native .rbxl scene; XML is preserved but never renamed")
    launcher_scene = None
    if launcher_scene_relative_path is not None:
        launcher_scene = validate_launcher_scene(source, before, launcher_scene_relative_path, explicit=True)
    elif create_launcher:
        launcher_scene = validate_launcher_scene(source, before, selection[2], explicit=False)
    report = {"schemaVersion": 1, "startedAtUtc": datetime.now(timezone.utc).isoformat(), "mode": "verify-existing" if verify_existing else "create", "source": str(source), "zip": str(archive), "sourceBeforeInventorySha256": inventory_hash(before), "sourceFiles": before, "status": "failed", "scope": "Byte integrity and package structure only; not gameplay, Studio loading, rights, or complete offline availability."}
    error = None
    try:
        if not verify_existing:
            metadata = {"schemaVersion": 1, "createdAtUtc": report["startedAtUtc"], "sceneRelativePath": selection[0], "metadataRelativePath": selection[1], "nativeSceneRelativePath": selection[2], "launcherCreated": create_launcher, "launcherSceneRelativePath": launcher_scene, "launcherSceneExplicit": launcher_scene_relative_path is not None, "sourceInventorySha256": inventory_hash(before), "scope": report["scope"]}
            generated = {METADATA: json_bytes(metadata)}
            if create_launcher:
                generated[LAUNCHER] = launcher_bytes(launcher_scene)
            records = dict(before)
            records.update({name: {"bytes": len(data), "sha256": sha_bytes(data)} for name, data in generated.items()})
            generated[MANIFEST] = json_bytes({"schemaVersion": 1, "algorithm": "sha256", "selfExcluded": [MANIFEST], "files": [{"path": name, **record} for name, record in sorted(records.items())]})
            with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zipped:
                for name in before:
                    check_path_chain(source / name)
                    zipped.write(source / name, name)
                for name, data in generated.items():
                    zipped.writestr(name, data)
        report["verification"] = verify_archive(source, archive, before, selection if not verify_existing else None, launcher_scene)
        report["zipFile"] = file_digest(archive)
    except (ArchiveError, OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        error = exc
        report["error"] = str(exc)
    finally:
        try:
            after = inventory(source)
            report["sourceAfterInventorySha256"] = inventory_hash(after)
            report["sourceUnchanged"] = after == before
            if after != before:
                error = ArchiveError("Source changed during packaging/verification; archive is not accepted")
                report["error"] = str(error)
        except (ArchiveError, OSError) as exc:
            error = exc
            report["error"] = str(exc)
            report["sourceUnchanged"] = False
        if error is None:
            report["status"] = "passed"
        report["finishedAtUtc"] = datetime.now(timezone.utc).isoformat()
        # Exclusive creation also protects an existing report against replacement.
        with report_path.open("xb") as handle:
            handle.write(json_bytes(report))
    if error:
        raise ArchiveError(f"{error}; failure report: {report_path}") from error
    return {"status": "passed", "zip": str(archive), "verification": str(report_path), "zipBytes": report["zipFile"]["bytes"], "zipSha256": report["zipFile"]["sha256"], "sourceUnchanged": True, **report["verification"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Reviewed source directory; never modified")
    parser.add_argument("--output", help="New external .zip path; never overwritten")
    parser.add_argument("--verify-existing", metavar="ZIP", help="Recheck an existing ZIP against the original source")
    parser.add_argument("--verification-output", help="New external JSON report path")
    parser.add_argument("--scene-relative-path")
    parser.add_argument("--metadata-relative-path")
    parser.add_argument("--native-scene-relative-path")
    parser.add_argument("--launcher-scene-relative-path", help="Explicit existing .rbxl/.rbxlx launch target; requires --create-launcher when creating, or asserts the target with --verify-existing")
    parser.add_argument("--create-launcher", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = package_archive(**vars(args))
    except (ArchiveError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
