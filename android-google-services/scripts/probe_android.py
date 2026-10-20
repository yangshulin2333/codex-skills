#!/usr/bin/env python3
"""Read-only, dependency-free ADB preflight. No installation or device changes."""

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path


UNKNOWN = "unknown"
PACKAGE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
PERMISSION_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)(?::\s*granted=(true|false))?")


def package_arg(value):
    if not PACKAGE_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("package names must contain only identifier components separated by dots")
    return value


def timeout_arg(value):
    try:
        result = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be a positive number")
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("timeout must be a positive finite number")
    return result


class Adb:
    def __init__(self, executable, serial, timeout, diagnostics):
        self.executable = executable
        self.serial = serial
        self.timeout = timeout
        self.diagnostics = diagnostics

    def run(self, args, query, targeted=True):
        command = [self.executable]
        if targeted:
            command.extend(["-s", self.serial])
        command.extend(args)
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace",
                                    timeout=self.timeout, shell=False)
        except subprocess.TimeoutExpired:
            self.diagnostics.append({"query": query, "status": "timeout"})
            return None
        except OSError:
            self.diagnostics.append({"query": query, "status": "could_not_start_adb"})
            return None
        if result.returncode != 0:
            # Deliberately omit stdout/stderr: they may contain private device data.
            self.diagnostics.append({"query": query, "status": "command_failed",
                                     "exit_code": result.returncode})
            return None
        return result.stdout.strip()

    def shell(self, args, query):
        output = self.run(["shell"] + args, query)
        # Some Android utilities print a failure but still return exit status 0.
        if output is not None and re.match(
                r"^(?:error:|Error:|Permission Denial:|Security exception:|"
                r"Exception occurred while executing|Unknown command:|Can't find service:|"
                r"cmd: Can't find service:|/system/bin/sh:)", output):
            self.diagnostics.append({"query": query, "status": "android_command_rejected"})
            return None
        return output


def parse_devices(output):
    devices = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("List of devices", "* daemon", "adb server")):
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        state = "no_permissions" if fields[1:3] == ["no", "permissions"] else fields[1]
        devices.append({"serial": fields[0], "state": state})
    return devices


def known_text(value):
    if value is None or not value.strip() or value.strip().lower() in ("null", "unknown"):
        return UNKNOWN
    return value.strip()


def integer(value):
    return int(value) if value is not None and re.fullmatch(r"\d+", value.strip()) else UNKNOWN


def toggle(value):
    number = integer(value)
    return bool(number) if number in (0, 1) else UNKNOWN


def parse_package(output, package, current_user):
    result = {
        "package_present": UNKNOWN,
        "version_code": UNKNOWN, "version_name": UNKNOWN,
        "min_sdk": UNKNOWN, "target_sdk": UNKNOWN,
        "flags": {"SYSTEM": UNKNOWN, "PRIVILEGED": UNKNOWN, "hwflags": UNKNOWN},
        "current_user": {"id": current_user, "state": UNKNOWN},
        "permissions": {},
    }
    if output is None:
        return result
    lines = output.splitlines()
    start = next((i for i, line in enumerate(lines)
                  if re.search(r"\bPackage \[" + re.escape(package) + r"\]", line)), None)
    if start is None:
        if re.search(r"(?:Unable to find package|Unknown package|not found)", output, re.I):
            result["package_present"] = False
        return result
    result["package_present"] = True
    base_indent = len(lines[start]) - len(lines[start].lstrip())
    block = []
    for line in lines[start + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= base_indent:
            break
        block.append(line)
    text = "\n".join(block)
    for key, pattern in (
        ("version_code", r"\bversionCode=(\d+)"),
        ("version_name", r"^\s*versionName=([^\r\n]+)"),
        ("min_sdk", r"\bminSdk=(\d+)"),
        ("target_sdk", r"\btargetSdk=(\d+)"),
    ):
        match = re.search(pattern, text, re.M)
        if match:
            result[key] = match.group(1).strip() if key == "version_name" else int(match.group(1))
    for field, names in (("SYSTEM", ("flags", "pkgFlags")),
                         ("PRIVILEGED", ("privateFlags", "privatePkgFlags"))):
        match = re.search(r"^\s*(?:" + "|".join(names) + r")=\[([^\]]*)\]", text, re.M)
        if match:
            tokens = re.split(r"[\s|,]+", match.group(1).strip())
            result["flags"][field] = field in tokens or "PRIVATE_FLAG_" + field in tokens
    match = re.search(r"^\s*hwflags=(\[[^\]\r\n]*\]|[^\s]+)", text, re.M | re.I)
    if match:
        value = match.group(1)
        if re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|\d+)", value):
            result["flags"]["hwflags"] = value
        elif value.startswith("[") and value.endswith("]"):
            tokens = [token for token in re.split(r"[\s|,]+", value[1:-1].strip()) if token]
            if all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token) for token in tokens):
                result["flags"]["hwflags"] = tokens

    requested = set()
    requested_seen = False
    grants = {}
    section = None
    section_indent = -1
    user = None
    for line in block:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        user_match = re.match(r"User (\d+):\s*(.*)", stripped)
        if user_match:
            user = int(user_match.group(1))
            section = None
            if user == current_user:
                state = {}
                for name in ("installed", "hidden", "suspended", "stopped", "notLaunched", "instant", "virtual"):
                    match = re.search(r"\b" + name + r"=(true|false)\b", user_match.group(2))
                    state[name] = match.group(1) == "true" if match else UNKNOWN
                match = re.search(r"\benabled=(\d+)\b", user_match.group(2))
                state["enabled_setting"] = int(match.group(1)) if match else UNKNOWN
                result["current_user"]["state"] = state
            continue
        if stripped in ("requested permissions:", "install permissions:", "runtime permissions:"):
            section = stripped.split()[0]
            section_indent = indent
            if section == "requested":
                requested_seen = True
            continue
        if not stripped:
            continue
        if section is not None and indent <= section_indent:
            section = None
        if section is None:
            continue
        match = PERMISSION_RE.fullmatch(stripped.split(",", 1)[0].strip())
        if not match:
            continue
        name, granted = match.groups()
        if section == "requested":
            requested.add(name)
        elif granted is not None and (section == "install" or (section == "runtime" and user == current_user)):
            grants[name] = (granted == "true", "install" if section == "install" else "runtime_current_user")
    for name in sorted(requested | grants.keys()):
        grant, source = grants.get(name, (UNKNOWN, UNKNOWN))
        result["permissions"][name] = {
            "requested": name in requested if requested_seen else UNKNOWN,
            "granted": grant, "grant_source": source,
        }
    return result


def parse_admins(output, packages):
    result = {package: {"query_status": "failed" if output is None else "parsed",
                        "active_admin_matches": []} for package in packages}
    if output is None:
        return result
    user = UNKNOWN
    enabled_indent = None
    for line in output.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        header = re.search(r"Enabled Device Admins\s*\(User\s+(\d+)", stripped, re.I)
        if header:
            user = int(header.group(1))
            enabled_indent = indent
            continue
        if enabled_indent is not None and stripped and indent <= enabled_indent:
            enabled_indent = None
            user = UNKNOWN
        active = re.search(r"\bActive admin\b", stripped, re.I)
        plain_component = enabled_indent is not None and re.fullmatch(r"[\w.]+/[\w.$]+:", stripped)
        if not active and not plain_component:
            continue
        match = re.search(r"([A-Za-z_][A-Za-z0-9_.]*)/([A-Za-z_.$][A-Za-z0-9_.$]*)", stripped)
        if match and match.group(1) in result:
            item = {"component": match.group(0), "user_id": user}
            matches = result[match.group(1)]["active_admin_matches"]
            if item not in matches:
                matches.append(item)
    return result


def probe(args):
    diagnostics = []
    report = {"schema_version": 1, "status": "error", "diagnostics": diagnostics}
    executable = shutil.which(args.adb or "adb")
    if executable is None:
        diagnostics.append({"query": "adb", "status": "not_found", "hint": "Use --adb PATH or add adb to PATH."})
        return report, 2
    adb = Adb(executable, args.serial, args.timeout, diagnostics)
    listing = adb.run(["devices"], "devices", targeted=False)
    if listing is None:
        return report, 2
    devices = parse_devices(listing)
    if args.list:
        report.update(status="complete", devices=devices)
        return report, 0
    if not args.serial:
        report["status"] = "refused"
        diagnostics.append({"query": "selection", "status": "serial_required",
                            "hint": "Run --list, then explicitly choose --serial SERIAL."})
        return report, 2
    selected = [device for device in devices if device["serial"] == args.serial]
    report["serial"] = args.serial
    if len(selected) != 1 or selected[0]["state"] != "device":
        state = selected[0]["state"] if len(selected) == 1 else "not_uniquely_found"
        report.update(status="refused", device_state=state)
        diagnostics.append({"query": "authorization", "status": "target_not_ready",
                            "hint": "Check the selected device, cable, and its USB debugging authorization."})
        return report, 2
    report["device_state"] = "device"

    prop_names = {
        "model": "ro.product.model", "build_display_id": "ro.build.display.id",
        "build_incremental": "ro.build.version.incremental",
        "android_release": "ro.build.version.release", "android_api": "ro.build.version.sdk",
        "abis": "ro.product.cpu.abilist", "timezone": "persist.sys.timezone",
    }
    device = {key: known_text(adb.shell(["getprop", prop], key)) for key, prop in prop_names.items()}
    device["android_api"] = integer(device["android_api"])
    if device["abis"] == UNKNOWN:
        device["abis"] = known_text(adb.shell(["getprop", "ro.product.cpu.abi"], "abi_fallback"))
    if device["abis"] != UNKNOWN:
        device["abis"] = [value.strip() for value in device["abis"].split(",") if value.strip()]
    current_user = integer(adb.shell(["am", "get-current-user"], "current_user"))
    device["current_user"] = current_user
    device["automatic_time"] = toggle(adb.shell(["settings", "get", "global", "auto_time"], "automatic_time"))
    device["automatic_timezone"] = toggle(adb.shell(["settings", "get", "global", "auto_time_zone"], "automatic_timezone"))
    device["rotation_baseline"] = {"accelerometer_rotation": UNKNOWN, "user_rotation": UNKNOWN}
    if current_user != UNKNOWN:
        for setting in device["rotation_baseline"]:
            value = adb.shell(["settings", "--user", str(current_user), "get", "system", setting], setting)
            device["rotation_baseline"][setting] = toggle(value) if setting == "accelerometer_rotation" else integer(value)
    else:
        diagnostics.append({"query": "current_user", "status": "unavailable",
                            "hint": "Per-user installation, runtime grants, and rotation queries were skipped."})
    report["device"] = device
    packages = {}
    for package in dict.fromkeys(args.package):
        output = adb.shell(["dumpsys", "package", package], "package:" + package)
        item = parse_package(output, package, current_user)
        item["installed_for_current_user"] = UNKNOWN
        if current_user != UNKNOWN:
            installed = adb.shell(["pm", "list", "packages", "--user", str(current_user), package], "installed:" + package)
            if installed is not None:
                rows = installed.splitlines()
                if all(not row.strip() or re.fullmatch(r"package:[A-Za-z_][A-Za-z0-9_.]*", row.strip()) for row in rows):
                    item["installed_for_current_user"] = "package:" + package in [row.strip() for row in rows]
                else:
                    diagnostics.append({"query": "installed:" + package, "status": "unrecognized_response"})
        if item["package_present"] == UNKNOWN:
            diagnostics.append({"query": "package:" + package, "status": "package_metadata_unavailable"})
        packages[package] = item
    report["packages"] = packages
    if args.admin_package:
        output = adb.shell(["dumpsys", "device_policy"], "active_admins")
        report["admin_packages"] = parse_admins(output, dict.fromkeys(args.admin_package))
    report["status"] = "partial" if diagnostics else "complete"
    return report, 1 if diagnostics else 0


def parser():
    result = argparse.ArgumentParser(description=__doc__, epilog=(
        "Only explicitly selected devices are queried. Output contains parsed fields only; "
        "raw dumps, accounts, logs, paths, and signature/compatibility conclusions are not saved. "
        "Unknown fields remain 'unknown'. An empty admin match list does not prove an admin is inactive. "
        "ADB may start its normal host daemon. This script does not issue write commands to Android."))
    result.add_argument("--adb", help="ADB executable path or executable name (default: discover adb in PATH)")
    result.add_argument("--list", action="store_true", help="only list device serials and connection states; do not run shell queries")
    result.add_argument("--serial", help="explicit target serial required for preflight, even with one connected device")
    result.add_argument("--package", action="append", default=[], type=package_arg, help="actual candidate package name; repeat as needed")
    result.add_argument("--admin-package", action="append", default=[], type=package_arg, help="package whose active-admin entries should be extracted; repeat as needed")
    result.add_argument("--timeout", type=timeout_arg, default=10.0, help="timeout in seconds for each command (default: 10)")
    result.add_argument("--out", type=Path, help="optional destination for the same parsed JSON printed to stdout")
    return result


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.serial and (args.serial.startswith("-") or re.search(r"\s|[\x00-\x1f\x7f]", args.serial)):
        cli.error("serial must be a nonempty device identifier without whitespace or control characters")
    report, code = probe(args)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        try:
            args.out.write_text(encoded, encoding="utf-8")
        except OSError:
            report["diagnostics"].append({"query": "output", "status": "could_not_write_json"})
            report["status"] = "partial" if code < 2 else report["status"]
            encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            code = max(code, 1)
    print(encoded, end="")
    return code


if __name__ == "__main__":
    sys.exit(main())
