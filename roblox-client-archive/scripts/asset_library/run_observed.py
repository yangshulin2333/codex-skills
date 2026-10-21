"""Preserve a real extraction command event, literal logs, exit and file hashes."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-inputs-only", action="store_true")
    parser.add_argument("--lune-executable", type=Path)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output is None and not args.check_inputs_only:
        parser.error("--output is required unless --check-inputs-only is used")
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    tool = Path(__file__).resolve().with_name("classify_downloaded_assets.py")
    command = [sys.executable, str(tool), "--archive", str(args.archive.resolve()), "--evidence-dir", str(evidence)]
    if args.output:
        command.extend(["--output", str(args.output.resolve())])
    if args.check_inputs_only:
        command.append("--check-inputs-only")
    if args.lune_executable:
        command.extend(["--lune-executable", str(args.lune_executable.resolve())])
    state_path = evidence / "command-execution.json"
    stdout_path, stderr_path = evidence / "classification-copy.stdout.log", evidence / "classification-copy.stderr.log"
    if state_path.exists():
        raise SystemExit("Observed execution already exists; choose a new evidence directory")
    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    state = {"command": command, "toolSha256": sha(tool), "events": [], "stdout": str(stdout_path), "stderr": str(stderr_path), "streamEncoding": "utf-8"}
    with stdout_path.open("xb") as out, stderr_path.open("xb") as err:
        process = subprocess.Popen(command, stdout=out, stderr=err, env=child_env)
        state["events"].append({"event": "command_execution", "pid": process.pid, "startedUtc": dt.datetime.now(dt.timezone.utc).isoformat()})
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(state["events"][-1]), flush=True)
        code = process.wait()
    state["events"].append({"event": "command_exit", "pid": process.pid, "exitStatus": code, "finishedUtc": dt.datetime.now(dt.timezone.utc).isoformat()})
    state["stdoutSha256"], state["stderrSha256"] = sha(stdout_path), sha(stderr_path)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    with (evidence / "VERIFICATION.txt").open("x", encoding="utf-8") as ledger:
        ledger.write(json.dumps(state, ensure_ascii=False, indent=2) + "\nLITERAL STDOUT BEGIN\n")
        ledger.write(stdout_path.read_text(encoding="utf-8", errors="replace"))
        ledger.write("\nLITERAL STDOUT END\nLITERAL STDERR BEGIN\n")
        ledger.write(stderr_path.read_text(encoding="utf-8", errors="replace"))
        ledger.write("\nLITERAL STDERR END\n")
    print(json.dumps({"event": "observed_extraction_complete", "exitStatus": code, "state": str(state_path)}), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
