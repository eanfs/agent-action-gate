# SPDX-License-Identifier: Apache-2.0
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", ".aag", "__pycache__", "dist", "build"}
def _fragment(*parts: str) -> re.Pattern[str]:
    return re.compile("".join(parts))


PATTERNS = (
    _fragment("/ho", "me/"),
    _fragment("/Us", "ers/"),
    _fragment("/work", "space"),
    _fragment("/opt/cur", "sor"),
    re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"),
    re.compile(r"BEGIN (?:OPENSSH|RSA|PRIVATE) KEY"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
)


class HygieneTest(unittest.TestCase):
    def test_tree_has_no_secrets_ips_or_local_paths(self):
        failures = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pattern in PATTERNS:
                if pattern.search(text):
                    failures.append(f"{path.relative_to(ROOT)} matches {pattern.pattern}")
        self.assertEqual(failures, [])
