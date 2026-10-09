import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pool.cli import main

ROOT = Path(__file__).resolve().parents[1]
FLAG = "--authorize-repository-access"


class GUIDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="pool-gui-command-")
        stage = Path(cls.temporary.name)
        script = stage / "main.swift"
        script.write_text('''import Foundation
let input = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [String: Any]
var result: [String: Any] = [:]
let command = input["command"] as! [String]
result["arguments"] = GUICommand.arguments(entry: input["entry"] as? String ?? "entry.py", config: input["config"] as? String ?? "config.json", command: command, userInitiated: input["userInitiated"] as? Bool ?? false)
if let output = input["output"] as? String {
 let f = GUIFailure(command: command, output: output, exitCode: Int32(input["exitCode"] as! Int), remaining: input["remaining"] as? Int, failed: input["failed"] as? Int)
 result["title"] = f.title; result["message"] = f.message
}
print(String(data: try JSONSerialization.data(withJSONObject: result), encoding: .utf8)!)
''')
        cls.binary = stage / "dispatch"
        subprocess.run(["/usr/bin/xcrun", "swiftc", "-module-cache-path", str(stage / "cache"),
                        str(ROOT / "source/macos/GUICommand.swift"), str(script), "-o", str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def invoke(self, command, **values):
        data = dict(command=command, **values)
        fixture = Path(self.temporary.name) / "request.json"
        fixture.write_text(json.dumps(data))
        return json.loads(subprocess.check_output([str(self.binary), str(fixture)], text=True))

    def test_confirmed_gui_upgrade_reaches_actual_cli_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.json"
            config.write_text("{}")
            args = self.invoke(["upgrade"], config=str(config), userInitiated=True)["arguments"]
            self.assertEqual(args.count(FLAG), 1)
            self.assertLess(args.index(FLAG), args.index("upgrade"))
            with patch.dict(os.environ, {}, clear=True), patch("pool.cli.Client"), patch("pool.cli.Brew") as brew, patch("pool.cli.Job") as job:
                job.return_value.report.return_value = {"failed_count": 0, "remaining_count": 0}
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(args[2:]), 0)
                brew.return_value.upgrade.assert_called_once()

    def test_unapproved_upgrade_is_still_blocked_before_adapter(self):
        args = self.invoke(["upgrade"], userInitiated=False)["arguments"]
        self.assertNotIn(FLAG, args)
        with patch("pool.cli.Brew") as brew, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(args[2:]), 3)
        brew.assert_not_called()

    def test_status_poll_does_not_authorize_repository_access(self):
        for human in (True, False):
            self.assertNotIn(FLAG, self.invoke(["status", "--json"], userInitiated=human)["arguments"])

    def test_retry_and_resume_receive_current_not_saved_authorization(self):
        for suffix in ("--retry-failed", "--resume"):
            command = ["upgrade", suffix]
            result = self.invoke(command, userInitiated=True)
            self.assertEqual(command, ["upgrade", suffix])
            self.assertEqual(result["arguments"].count(FLAG), 1)
            self.assertEqual(result["arguments"][-2:], command)

    def test_other_explicit_gui_actions_use_same_dispatch(self):
        for action in ("install", "repair", "maintenance", "capture", "compatibility", "imports"):
            self.assertIn(FLAG, self.invoke([action], userInitiated=True)["arguments"])
        for action in ("sync", "job", "settings"):
            self.assertNotIn(FLAG, self.invoke([action], userInitiated=True)["arguments"])

    def test_early_failure_displays_reason_without_invented_queue(self):
        result = self.invoke(["upgrade"], output="Blocked: repository authorization missing.\n", exitCode=3)
        self.assertEqual(result["title"], "Update & Upgrade failed")
        self.assertEqual(result["message"], "Blocked: repository authorization missing.")
        self.assertNotIn("saved", result["message"])

    def test_reported_queue_failure_keeps_count_and_real_diagnostic(self):
        result = self.invoke(["upgrade"], output="HOMEBREW_POOL_PROCESS_GROUP=123\nError: compiler failed\nHOMEBREW_POOL_RUN_STATE={}\n",
                             exitCode=1, remaining=10, failed=1)
        self.assertEqual(result["title"], "Paused — Error")
        self.assertIn("Error: compiler failed", result["message"])
        self.assertIn("10 remaining", result["message"])
        self.assertNotIn("PROCESS_GROUP", result["message"])

    def test_empty_failure_reports_exit_code(self):
        result = self.invoke(["upgrade"], output="", exitCode=7)
        self.assertEqual(result["message"], "The command exited with code 7.")
