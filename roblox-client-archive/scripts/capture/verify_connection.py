#!/usr/bin/env python3
"""Verify correlation among saved diagnostic and log inputs offline.

The capture directory must contain diagnostic.json and diagnostic-probe.txt.
A UI success toast or an Attach ping alone is insufficient. This verifier binds
the saved files to one Place/Universe, one PID's fresh Attach event, and the
same diagnostic token in Player CreatorOutput. A passing result establishes
content correlation only: this tool cannot verify that the diagnostic and
Player log belong to the OS process identified by the native PID. The operator
must establish that ownership separately through trusted live observation or
tools before accepting an operational connection gate. No live connection is
probed. Logs and diagnostic account fields are omitted from the JSON report.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re


UTC = dt.timezone.utc
CLOCK_TOLERANCE_SECONDS = 5
TOKEN = re.compile(r"ARCHIVE_PROBE_([0-9]+)\Z")
NATIVE_STAMP = re.compile(r"^\[([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?)\]")
NATIVE_PID = re.compile(r"\[(?:[^\]\r\n]*\(([0-9]+)\)|([0-9]+))\]\s*:")
PLAYER_STAMP = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})),")
PLAYER_MESSAGE = re.compile(r"\[FLog::CreatorOutput\]\s+(ARCHIVE_PROBE_[0-9]+)\s+REAL_CLIENT_EXECUTION_CONFIRMED\s*\Z")
FAILURE_PATTERNS = (
    ("internal-function-instruction", re.compile(r"Failed to find (?:a|an) internal function instruction", re.I)),
    ("core-module-unavailable", re.compile(r"Could not find a CoreModule", re.I)),
    ("client-not-attached", re.compile(r"Client is not attached", re.I)),
    ("attach-failed", re.compile(r"\b(?:Attach failed|Failed to attach)\b", re.I)),
    ("client-attach-ping-network-failed", re.compile(r"Client is attached but failed to ping the server due to unstable network", re.I)),
    ("client-success-ping-timeout", re.compile(r"Still did not receive the success ping from client\. Treating this as failed\.", re.I)),
)


def utc_text(value: dt.datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def offset_text(value: dt.timezone) -> str:
    minutes = int(value.utcoffset(None).total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, remainder = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}:{remainder:02d}"


def aware_iso(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("expected a timezone-aware ISO timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include Z or an explicit UTC offset")
    return parsed.astimezone(UTC)


def explicit_offset(value: str) -> dt.timezone:
    match = re.fullmatch(r"([+-])([0-9]{2}):([0-9]{2})", value)
    if not match or int(match[2]) > 23 or int(match[3]) > 59:
        raise argparse.ArgumentTypeError("UTC offset must use +HH:MM or -HH:MM, less than 24 hours")
    minutes = (int(match[2]) * 60 + int(match[3])) * (1 if match[1] == "+" else -1)
    return dt.timezone(dt.timedelta(minutes=minutes))


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a positive integer") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def _artifact(path: Path, role: str, report: dict) -> bytes | None:
    try:
        data = path.read_bytes()
    except OSError:
        report["errors"].append(role + ":unreadable-or-missing")
        return None
    report["artifacts"][role] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return data


def _native_events(data: bytes, pid: int, offset: dt.timezone) -> tuple[list, list]:
    events, bad_lines = [], []
    for number, line in enumerate(data.decode("utf-8-sig", errors="replace").splitlines(), 1):
        match = NATIVE_PID.search(line)
        if not match or int(match[1] or match[2]) != pid:
            continue
        reasons = [code for code, pattern in FAILURE_PATTERNS if pattern.search(line)]
        success = "Attach ping received from client" in line
        if not success and not reasons:
            continue
        stamp = NATIVE_STAMP.match(line)
        try:
            moment = dt.datetime.fromisoformat(stamp[1]).replace(tzinfo=offset).astimezone(UTC) if stamp else None
        except ValueError:
            moment = None
        if moment is None:
            bad_lines.append(number)
            continue
        # A contradictory line must be treated as a failure, never as success.
        events.append({"line": number, "time": moment, "success": success and not reasons, "reasonCodes": reasons})
    return events, bad_lines


def _player_events(data: bytes, token: str) -> tuple[list, list]:
    events, bad_lines = [], []
    for number, line in enumerate(data.decode("utf-8-sig", errors="replace").splitlines(), 1):
        message = PLAYER_MESSAGE.search(line)
        if not message or message[1] != token:
            continue
        stamp = PLAYER_STAMP.match(line)
        try:
            moment = aware_iso(stamp[1]) if stamp else None
        except argparse.ArgumentTypeError:
            moment = None
        if moment is None:
            bad_lines.append(number)
        else:
            events.append({"line": number, "time": moment})
    return events, bad_lines


def _event_summary(event: dict) -> dict:
    result = {"line": event["line"], "timeUtc": utc_text(event["time"])}
    if event.get("reasonCodes"):
        result["reasonCodes"] = event["reasonCodes"]
    return result


def verify_connection(capture: Path, place_id: int, universe_id: int,
                      native_log: Path, native_log_utc_offset: dt.timezone,
                      player_log: Path, pid: int, not_before: dt.datetime) -> dict:
    """Return content correlation, without OS-process ownership or live checks."""
    report = {
        "schemaVersion": 1,
        "placeId": place_id,
        "universeId": universe_id,
        "pid": pid,
        "notBeforeUtc": utc_text(not_before),
        "nativeLogUtcOffset": offset_text(native_log_utc_offset),
        "clockToleranceSeconds": CLOCK_TOLERANCE_SECONDS,
        "passed": False,
        "historicalExecutionVerified": False,
        "processInputOwnershipChecked": False,
        "operationalGateChecked": False,
        "liveConnectionChecked": False,
        "currentConnectionClaimed": False,
        "completeExportChecked": False,
        "laterFailureObserved": False,
        "artifacts": {},
        "errors": [],
        "scope": "Offline correlation of supplied content only: Place/Universe, token, timing and supplied native PID. passed and historicalExecutionVerified do not verify diagnostic/Player-log OS process ownership or an operational connection gate. The operator must independently establish trusted input ownership. No live connection, complete export or log authenticity check.",
    }
    blobs = {
        "diagnostic": _artifact(capture / "diagnostic.json", "diagnostic", report),
        "diagnosticProbe": _artifact(capture / "diagnostic-probe.txt", "diagnosticProbe", report),
        "nativeLog": _artifact(native_log, "nativeLog", report),
        "playerLog": _artifact(player_log, "playerLog", report),
    }
    if blobs["diagnostic"] is None:
        return report
    try:
        diagnostic = json.loads(blobs["diagnostic"].decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        report["errors"].append("diagnostic:invalid-json")
        return report
    if not isinstance(diagnostic, dict):
        report["errors"].append("diagnostic:expected-object")
        return report
    if type(diagnostic.get("placeId")) is not int or diagnostic["placeId"] != place_id:
        report["errors"].append("diagnostic:place-id-mismatch")
    if type(diagnostic.get("universeId")) is not int or diagnostic["universeId"] != universe_id:
        report["errors"].append("diagnostic:universe-id-mismatch")
    if diagnostic.get("loaded") is not True:
        report["errors"].append("diagnostic:client-not-loaded")
    token = diagnostic.get("diagnosticToken")
    match = TOKEN.fullmatch(token) if isinstance(token, str) else None
    if not match:
        report["errors"].append("diagnostic:invalid-token")
        return report
    try:
        token_time = dt.datetime.fromtimestamp(int(match[1]), UTC)
    except (ValueError, OverflowError, OSError):
        report["errors"].append("diagnostic:invalid-token-epoch")
        return report
    report["diagnostic"] = {"loaded": diagnostic.get("loaded") is True, "token": token, "tokenTimeUtc": utc_text(token_time)}
    if blobs["diagnosticProbe"] is not None and blobs["diagnosticProbe"] != token.encode("utf-8"):
        report["errors"].append("diagnosticProbe:token-mismatch")
    if blobs["nativeLog"] is None or blobs["playerLog"] is None:
        return report
    native, bad_native = _native_events(blobs["nativeLog"], pid, native_log_utc_offset)
    player, bad_player = _player_events(blobs["playerLog"], token)
    if bad_native:
        report["nativeTimestampErrorLines"] = bad_native
        report["errors"].append("nativeLog:unparseable-relevant-timestamp")
    if bad_player:
        report["playerTimestampErrorLines"] = bad_player
        report["errors"].append("playerLog:unparseable-token-timestamp")
    fresh_player = [event for event in player if event["time"] >= not_before]
    timed_player = [event for event in fresh_player if abs((event["time"] - token_time).total_seconds()) <= CLOCK_TOLERANCE_SECONDS]
    if not timed_player:
        if not player:
            report["errors"].append("playerLog:confirmed-token-not-found")
        elif not fresh_player:
            report["errors"].append("playerLog:confirmed-token-before-not-before")
        else:
            report["errors"].append("playerLog:token-clock-mismatch")
        return report
    execution = min(timed_player, key=lambda event: (event["time"], event["line"]))
    report["playerExecution"] = _event_summary(execution)
    report["tokenClockDifferenceSeconds"] = round((execution["time"] - token_time).total_seconds(), 6)
    fresh_attach = [event for event in native if event["success"] and not_before <= event["time"] <= execution["time"]]
    later = [event for event in native if event["reasonCodes"] and event["time"] > execution["time"]]
    report["laterFailureObserved"] = bool(later)
    report["laterFailures"] = [_event_summary(event) for event in later]
    if not fresh_attach:
        report["errors"].append("nativeLog:no-fresh-specified-pid-attach-before-execution")
        return report
    attach = max(fresh_attach, key=lambda event: (event["time"], event["line"]))
    report["nativeAttach"] = _event_summary(attach)
    between = [event for event in native if event["reasonCodes"]
               and (event["time"], event["line"]) > (attach["time"], attach["line"])
               and event["time"] <= execution["time"]]
    report["failuresBetweenAttachAndExecution"] = [_event_summary(event) for event in between]
    if between:
        report["errors"].append("nativeLog:attach-failure-before-execution")
    report["historicalExecutionVerified"] = not report["errors"]
    report["passed"] = report["historicalExecutionVerified"]
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--place-id", type=positive_int, required=True)
    parser.add_argument("--universe-id", type=positive_int, required=True)
    parser.add_argument("--native-log", type=Path, required=True)
    parser.add_argument("--native-log-utc-offset", type=explicit_offset, required=True)
    parser.add_argument("--player-log", type=Path, required=True)
    parser.add_argument("--pid", type=positive_int, required=True)
    parser.add_argument("--not-before", type=aware_iso, required=True)
    parser.add_argument("--output", type=Path, help="New JSON report; existing files are never replaced")
    args = parser.parse_args(argv)
    if args.output is not None and (args.output.exists() or not args.output.parent.is_dir()):
        parser.error("output must be a new file in an existing directory")
    report = verify_connection(args.capture, args.place_id, args.universe_id,
                               args.native_log, args.native_log_utc_offset,
                               args.player_log, args.pid, args.not_before)
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)
    if args.output is not None:
        try:
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded + "\n")
        except OSError:
            parser.error("cannot exclusively create the output report")
    print(encoded)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
