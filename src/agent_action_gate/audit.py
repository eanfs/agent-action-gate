# SPDX-License-Identifier: Apache-2.0
"""Append-only JSONL audit log."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path


class AuditError(ValueError):
    """The audit log cannot be read or written."""


class AuditLog:
    def __init__(self, path: str | None):
        if path is not None and (path.strip() != path or "\n" in path or "\x00" in path):
            raise AuditError("审计路径无效")
        self.path = path
        self._memory: list[dict] | None = [] if path is None else None

    def reset(self) -> None:
        if self.path is None:
            self._memory = []
            return
        target = Path(self.path)
        if target.exists() and target.is_dir():
            raise AuditError(f"审计路径是目录: {self.path}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        except OSError as exc:
            raise AuditError(f"无法写入审计日志: {self.path}") from exc

    def append(self, record: dict) -> dict:
        stored = copy.deepcopy(record)
        stored["id"] = f"dec_{len(self.read()) + 1:03d}"
        stored["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = json.dumps(stored, ensure_ascii=False, sort_keys=True)
        if "\n" in line:
            raise AuditError("审计记录不能换行")
        if self.path is None:
            assert self._memory is not None
            self._memory.append(stored)
        else:
            target = Path(self.path)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError as exc:
                raise AuditError(f"无法写入审计日志: {self.path}") from exc
        return copy.deepcopy(stored)

    def read(self) -> list[dict]:
        if self.path is None:
            assert self._memory is not None
            return copy.deepcopy(self._memory)
        target = Path(self.path)
        if not target.exists():
            return []
        if target.is_dir():
            raise AuditError(f"审计路径是目录: {self.path}")
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise AuditError(f"无法读取审计日志: {self.path}") from exc
        records: list[dict] = []
        for lineno, line in enumerate(raw.splitlines(), 1):
            if line.strip() == "":
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AuditError(f"审计日志第 {lineno} 行不是 JSON 对象") from exc
            if not isinstance(item, dict):
                raise AuditError(f"审计日志第 {lineno} 行不是 JSON 对象")
            records.append(item)
        return records
