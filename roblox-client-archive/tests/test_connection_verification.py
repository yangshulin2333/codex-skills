"""Evidence tests use temporary fixtures, never a live client or network."""
import contextlib
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "capture" / "verify_connection.py"
SPEC = importlib.util.spec_from_file_location("archive_verify_connection", SCRIPT)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
UTC = dt.timezone.utc


class ConnectionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root / "capture"
        self.capture.mkdir()
        self.native = self.root / "native.log"
        self.player = self.root / "player.log"
        self.epoch = int(dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC).timestamp())
        self.token = "ARCHIVE_PROBE_" + str(self.epoch)
        self.diag = {"placeId": 111, "universeId": 222, "loaded": True,
                     "diagnosticToken": self.token, "playerName": "PRIVATE_ACCOUNT_SENTINEL"}
        self.write_diag()
        (self.capture / "diagnostic-probe.txt").write_text(self.token, encoding="utf-8")
        self.native.write_text(self.attach("2026-01-02 11:04:00.000"), encoding="utf-8")
        self.player.write_text(self.player_line("2026-01-02T03:04:05.500Z"), encoding="utf-8")

    def write_diag(self):
        (self.capture / "diagnostic.json").write_text(json.dumps(self.diag), encoding="utf-8")

    def attach(self, stamp, pid=333, named=True):
        label = "PRIVATE_ACCOUNT_SENTINEL (" + str(pid) + ")" if named else str(pid)
        return f'[{stamp}] [RBXClient] [trace] [{label}]: Attach ping received from client "PRIVATE_ACCOUNT_SENTINEL", This indicates everything was successful.\n'

    def failure(self, stamp, pid=333):
        return f"[{stamp}] [Execution] [error] [{pid}]: Could not find a CoreModule; Client is not attached\n"

    def player_line(self, stamp, token=None, marker="FLog::CreatorOutput"):
        return f"{stamp},1.000,1234,6,Info [{marker}] {token or self.token} REAL_CLIENT_EXECUTION_CONFIRMED\n"

    def args(self):
        return ["--capture", str(self.capture), "--place-id", "111", "--universe-id", "222",
                "--native-log", str(self.native), "--native-log-utc-offset", "+08:00",
                "--player-log", str(self.player), "--pid", "333", "--not-before", "2026-01-02T03:03:00Z"]

    def run_cli(self, args=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = VERIFY.main(args if args is not None else self.args())
        return code, json.loads(output.getvalue())

    def test_real_evidence_accepts_named_pid_without_disclosing_account(self):
        self.native.write_text("unrelated PRIVATE_COOKIE_SENTINEL\n" + self.native.read_text(encoding="utf-8"), encoding="utf-8")
        code, report = self.run_cli()
        self.assertEqual(code, 0)
        self.assertTrue(report["passed"])
        self.assertEqual(report["nativeAttach"]["line"], 2)
        self.assertEqual(report["nativeAttach"]["timeUtc"], "2026-01-02T03:04:00.000Z")
        self.assertEqual(report["nativeLogUtcOffset"], "+08:00")
        self.assertFalse(report["liveConnectionChecked"])
        self.assertFalse(report["processInputOwnershipChecked"])
        self.assertFalse(report["operationalGateChecked"])
        self.assertFalse(report["currentConnectionClaimed"])
        self.assertFalse(report["completeExportChecked"])
        self.assertNotIn("PRIVATE_", json.dumps(report))
        self.assertEqual(len(report["artifacts"]["nativeLog"]["sha256"]), 64)

    def test_cross_process_fixture_only_reports_content_correlation(self):
        # Fixture ownership is known to the test author, not encoded by an
        # authenticated link in these saved artifacts. Client B can emit the
        # same second-based token as client A in the same Place/Universe.
        other_capture = self.root / "client-b-capture"
        other_capture.mkdir()
        other_diag = dict(self.diag, playerName="CLIENT_B_PRIVATE_SENTINEL")
        (other_capture / "diagnostic.json").write_text(json.dumps(other_diag), encoding="utf-8")
        (other_capture / "diagnostic-probe.txt").write_text(self.token, encoding="utf-8")
        other_player = self.root / "client-b-player.log"
        other_player.write_text(self.player_line("2026-01-02T03:04:05.500Z"), encoding="utf-8")
        args = self.args()
        args[args.index("--capture") + 1] = str(other_capture)
        args[args.index("--player-log") + 1] = str(other_player)
        code, report = self.run_cli(args)
        self.assertEqual(code, 0)  # Correlation is real; process ownership is unknown.
        self.assertTrue(report["passed"])
        self.assertTrue(report["historicalExecutionVerified"])
        self.assertFalse(report["processInputOwnershipChecked"])
        self.assertFalse(report["operationalGateChecked"])
        self.assertFalse(report["currentConnectionClaimed"])
        self.assertIn("do not verify diagnostic/Player-log OS process ownership", report["scope"])
        self.assertNotIn("CLIENT_B_PRIVATE_SENTINEL", json.dumps(report))

    def test_ui_success_without_diagnostic_files_fails(self):
        (self.capture / "diagnostic.json").unlink()
        (self.capture / "diagnostic-probe.txt").unlink()
        self.native.write_text("Script executed successfully on 1 client(s)!\n", encoding="utf-8")
        code, report = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("diagnostic:unreadable-or-missing", report["errors"])

    def test_probe_token_must_match_bytes_exactly(self):
        for body in ["ARCHIVE_PROBE_1", self.token + "\n"]:
            with self.subTest(body=body):
                (self.capture / "diagnostic-probe.txt").write_text(body, encoding="utf-8")
                code, report = self.run_cli()
                self.assertEqual(code, 1)
                self.assertIn("diagnosticProbe:token-mismatch", report["errors"])

    def test_wrong_project_or_not_loaded_fails(self):
        for field, value, error in [("placeId", 999, "diagnostic:place-id-mismatch"),
                                    ("universeId", 999, "diagnostic:universe-id-mismatch"),
                                    ("loaded", False, "diagnostic:client-not-loaded")]:
            original = self.diag[field]
            with self.subTest(field=field):
                self.diag[field] = value
                self.write_diag()
                code, report = self.run_cli()
                self.assertEqual(code, 1)
                self.assertIn(error, report["errors"])
            self.diag[field] = original
        self.write_diag()

    def test_wrong_pid_attach_cannot_pass(self):
        self.native.write_text(self.attach("2026-01-02 11:04:00.000", pid=444), encoding="utf-8")
        code, report = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("nativeLog:no-fresh-specified-pid-attach-before-execution", report["errors"])

    def test_plain_pid_and_explicit_timezone_conversion(self):
        self.native.write_text(self.attach("2026-01-01 23:04:00.000", named=False), encoding="utf-8")
        args = self.args()
        pos = args.index("--native-log-utc-offset")
        args[pos:pos + 2] = ["--native-log-utc-offset=-04:00"]
        code, report = self.run_cli(args)
        self.assertEqual(code, 0)
        self.assertEqual(report["nativeAttach"]["timeUtc"], "2026-01-02T03:04:00.000Z")

    def test_wrong_timezone_and_attach_after_execution_fail(self):
        self.native.write_text(self.attach("2026-01-02 11:04:06.000"), encoding="utf-8")
        code, report = self.run_cli()
        self.assertEqual(code, 1)
        self.assertNotIn("nativeAttach", report)
        self.native.write_text(self.attach("2026-01-02 11:04:00.000"), encoding="utf-8")
        args = self.args()
        args[args.index("+08:00")] = "+00:00"
        code, _ = self.run_cli(args)
        self.assertEqual(code, 1)

    def test_stale_attach_before_gate_fails(self):
        self.native.write_text(self.attach("2026-01-02 11:02:59.999"), encoding="utf-8")
        code, report = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("nativeLog:no-fresh-specified-pid-attach-before-execution", report["errors"])

    def test_stale_execution_before_gate_fails(self):
        args = self.args()
        args[-1] = "2026-01-02T03:04:06Z"
        code, report = self.run_cli(args)
        self.assertEqual(code, 1)
        self.assertIn("playerLog:confirmed-token-before-not-before", report["errors"])

    def test_player_requires_exact_token_and_creator_output(self):
        for line in [self.player_line("2026-01-02T03:04:05Z", "ARCHIVE_PROBE_1"),
                     self.player_line("2026-01-02T03:04:05Z", marker="FLog::OtherOutput"),
                     self.player_line("2026-01-02T03:04:05Z").rstrip() + " EXTRA\n"]:
            with self.subTest(line=line):
                self.player.write_text(line, encoding="utf-8")
                code, report = self.run_cli()
                self.assertEqual(code, 1)
                self.assertIn("playerLog:confirmed-token-not-found", report["errors"])

    def test_token_time_tolerance_has_a_boundary(self):
        self.player.write_text(self.player_line("2026-01-02T03:04:10Z"), encoding="utf-8")
        self.assertEqual(self.run_cli()[0], 0)
        self.player.write_text(self.player_line("2026-01-02T03:04:10.001Z"), encoding="utf-8")
        code, report = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("playerLog:token-clock-mismatch", report["errors"])

    def test_failure_after_attach_before_execution_rejects(self):
        with self.native.open("a", encoding="utf-8") as stream:
            stream.write(self.failure("2026-01-02 11:04:03.000"))
        code, report = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("nativeLog:attach-failure-before-execution", report["errors"])
        self.assertEqual(report["failuresBetweenAttachAndExecution"][0]["line"], 2)

    def test_later_failure_does_not_erase_observed_execution(self):
        with self.native.open("a", encoding="utf-8") as stream:
            stream.write(self.failure("2026-01-02 11:04:06.000"))
        code, report = self.run_cli()
        self.assertEqual(code, 0)
        self.assertTrue(report["historicalExecutionVerified"])
        self.assertTrue(report["laterFailureObserved"])
        self.assertFalse(report["currentConnectionClaimed"])

    def test_explicit_attach_ping_failures_before_execution_reject(self):
        failures = [
            ("Client is attached but failed to ping the server due to unstable network", "client-attach-ping-network-failed"),
            ("Still did not receive the success ping from client. Treating this as failed.", "client-success-ping-timeout"),
        ]
        for message, reason in failures:
            with self.subTest(reason=reason):
                self.native.write_text(self.attach("2026-01-02 11:04:00.000") +
                                       f"[2026-01-02 11:04:03.000] [RBXClient] [error] [333]: {message}\n", encoding="utf-8")
                code, report = self.run_cli()
                self.assertEqual(code, 1)
                self.assertIn("nativeLog:attach-failure-before-execution", report["errors"])
                self.assertEqual(report["failuresBetweenAttachAndExecution"][0]["reasonCodes"], [reason])
                self.assertFalse(report["laterFailureObserved"])

    def test_explicit_attach_ping_failures_after_execution_only_flag_later(self):
        failures = [
            ("Client is attached but failed to ping the server due to unstable network", "client-attach-ping-network-failed"),
            ("Still did not receive the success ping from client. Treating this as failed.", "client-success-ping-timeout"),
        ]
        for message, reason in failures:
            with self.subTest(reason=reason):
                self.native.write_text(self.attach("2026-01-02 11:04:00.000") +
                                       f"[2026-01-02 11:04:06.000] [RBXClient] [error] [333]: {message}\n", encoding="utf-8")
                code, report = self.run_cli()
                self.assertEqual(code, 0)
                self.assertTrue(report["historicalExecutionVerified"])
                self.assertTrue(report["laterFailureObserved"])
                self.assertEqual(report["laterFailures"][0]["reasonCodes"], [reason])
                self.assertEqual(report["failuresBetweenAttachAndExecution"], [])
                self.assertFalse(report["currentConnectionClaimed"])

    def test_old_failure_and_other_pid_failure_are_not_current_failures(self):
        original = self.native.read_text(encoding="utf-8")
        self.native.write_text(self.failure("2026-01-02 11:02:00.000") + original + self.failure("2026-01-02 11:04:03.000", pid=444), encoding="utf-8")
        self.assertEqual(self.run_cli()[0], 0)

    def test_unrelated_failed_warning_is_not_an_attach_failure(self):
        with self.native.open("a", encoding="utf-8") as stream:
            stream.write("[2026-01-02 11:04:03.000] [Downloader] [warning] [333]: Failed to load optional image\n")
        code, report = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(report["failuresBetweenAttachAndExecution"], [])
        self.assertFalse(report["laterFailureObserved"])

    def test_new_attach_can_recover_after_an_earlier_failure(self):
        with self.native.open("a", encoding="utf-8") as stream:
            stream.write(self.failure("2026-01-02 11:04:01.000"))
            stream.write(self.attach("2026-01-02 11:04:02.000"))
        code, report = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(report["nativeAttach"]["line"], 3)

    def test_same_timestamp_native_events_follow_line_order(self):
        stamp = "2026-01-02 11:04:00.000"
        self.native.write_text(self.failure(stamp) + self.attach(stamp), encoding="utf-8")
        self.assertEqual(self.run_cli()[0], 0)
        self.native.write_text(self.attach(stamp) + self.failure(stamp), encoding="utf-8")
        self.assertEqual(self.run_cli()[0], 1)

    def test_malformed_relevant_timestamp_cannot_hide_failure(self):
        with self.native.open("a", encoding="utf-8") as stream:
            stream.write(self.failure("INVALID"))
        code, report = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("nativeLog:unparseable-relevant-timestamp", report["errors"])

    def test_invalid_json_and_invalid_token_are_failures(self):
        (self.capture / "diagnostic.json").write_text("not JSON", encoding="utf-8")
        self.assertEqual(self.run_cli()[0], 1)
        self.diag["diagnosticToken"] = "ARCHIVE_PROBE_999999999999999999999999999"
        self.write_diag()
        self.assertEqual(self.run_cli()[0], 1)

    def test_cli_parameters_and_output_exclusive_creation(self):
        for option, value in [("--not-before", "2026-01-02T03:03:00"),
                              ("--native-log-utc-offset", "+24:00"), ("--pid", "0")]:
            args = self.args()
            args[args.index(option) + 1] = value
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    VERIFY.main(args)
                self.assertEqual(error.exception.code, 2)
        output = self.root / "report.json"
        code, report = self.run_cli(self.args() + ["--output", str(output)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)
        pristine = output.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                VERIFY.main(self.args() + ["--output", str(output)])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(output.read_bytes(), pristine)

    def test_subprocess_returns_evidence_failure_exit_one(self):
        (self.capture / "diagnostic-probe.txt").unlink()
        result = subprocess.run([sys.executable, "-B", str(SCRIPT)] + self.args(), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["passed"])
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
