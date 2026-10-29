# SPDX-License-Identifier: Apache-2.0
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(args, cwd, stdin=None):
    env = os.environ.copy()
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src if not env.get("PYTHONPATH") else src + os.pathsep + env["PYTHONPATH"]
    return subprocess.run(
        [sys.executable, "-m", "agent_action_gate", *args],
        cwd=cwd,
        env=env,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def _section(name: str) -> str:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start = f"<!-- verify:{name} -->"
    end = f"<!-- /verify:{name} -->"
    if start not in text or end not in text:
        raise AssertionError(f"README is missing {name}")
    body = text.split(start, 1)[1].split(end, 1)[0].strip()
    lines = body.splitlines()
    if not lines or not lines[0].startswith("```") or not lines[-1].startswith("```"):
        raise AssertionError(f"README section {name} is not a fenced block")
    content = "\n".join(lines[1:-1])
    if not content.endswith("\n"):
        content += "\n"
    return content


class CliTest(unittest.TestCase):
    def test_demo_replay_and_second_run_resets_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = _run(["demo", "refund"], tmp)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stderr, "")
            self.assertEqual(first.stdout, _section("demo-stdout"))
            self.assertNotIn(tmp, first.stdout)
            replay = _run(["replay"], tmp)
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertEqual(replay.stdout, _section("replay-stdout"))
            one = _run(["replay", "dec_002"], tmp)
            self.assertEqual(one.returncode, 0)
            self.assertIn("dec_002", one.stdout)
            self.assertNotIn("dec_001", one.stdout)
            self.assertNotIn("dec_003", one.stdout)
            missing = _run(["replay", "dec_999"], tmp)
            self.assertEqual(missing.returncode, 2)
            again = _run(["demo", "refund"], tmp)
            self.assertEqual(again.returncode, 0)
            lines = [
                json.loads(line)
                for line in Path(tmp, ".aag", "audit.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([item["id"] for item in lines], ["dec_001", "dec_002", "dec_003"])

    def test_interactive_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            denied = _run(["demo", "refund", "--interactive"], tmp, stdin="n\n")
            self.assertEqual(denied.returncode, 0, denied.stderr)
            self.assertIn("mode=interactive", denied.stdout)
            self.assertIn("denied approver=interactive-operator", denied.stdout)
            self.assertIn("[2/3]", denied.stdout)
            approved = _run(["demo", "refund", "--interactive"], tmp, stdin="y\n")
            self.assertEqual(approved.returncode, 0, approved.stderr)
            self.assertIn("approved approver=interactive-operator mode=interactive", approved.stdout)
            self.assertIn("审批 refund", approved.stderr)

    def test_eval_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = _run(["eval"], tmp)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("16 passed, 0 failed, pass_rate=1.000, threshold=1.000", ok.stdout)
            self.assertFalse(Path(tmp, ".aag").exists())
            low = _run(["eval", "--threshold", "1.01"], tmp)
            self.assertEqual(low.returncode, 1)
            self.assertIn("threshold=1.010", low.stdout)
            bad = _run(["eval", "--threshold", "-1"], tmp)
            self.assertEqual(bad.returncode, 2)
            self.assertNotIn("PASS ", bad.stdout)

    def test_readme_library_snippet_and_quickstart_commands(self):
        snippet = _section("library")
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                exec(snippet, {})
            finally:
                os.chdir(previous)
            self.assertTrue(Path(tmp, ".aag", "audit.jsonl").is_file())
        quickstart = _section("quickstart")
        commands = [line for line in quickstart.splitlines() if line.strip() and not line.startswith("#")]
        self.assertEqual(
            commands,
            [
                "git clone https://github.com/eanfs/agent-action-gate.git",
                "cd agent-action-gate",
                "python3 -m venv .venv",
                ".venv/bin/python -m pip install .",
                ".venv/bin/aag demo refund",
                ".venv/bin/aag replay",
                ".venv/bin/aag eval",
            ],
        )

    def test_missing_audit_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = _run(["replay"], tmp)
            self.assertEqual(missing.returncode, 2)
            self.assertIn(".aag/audit.jsonl", missing.stderr)
            self.assertNotIn(tmp, missing.stderr)
