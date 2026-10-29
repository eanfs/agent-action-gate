# SPDX-License-Identifier: Apache-2.0
"""Stable text rendering for demo output and replay."""

from __future__ import annotations

import json
import re


def format_params(params: dict) -> str:
    parts: list[str] = []
    for key in sorted(params):
        parts.append(f"{key}={_format_value(params[key])}")
    return " ".join(parts)


def format_record(record: dict, prefix: str = "") -> str:
    params = format_params(record.get("params") or {})
    head = f"{prefix}{record['id']}  {record['action']}"
    if params:
        head = f"{head}  {params}"
    lines = [
        head,
        f"  策略: {record['decision']}",
        f"  规则: {record['rule']}",
        f"  原因: {record['reason']}",
    ]
    approval = record.get("approval")
    if approval:
        lines.append(
            "  审批: "
            f"{approval['outcome']} approver={approval['approver']} mode={approval['mode']}"
        )
    executed = "已执行" if record.get("executed") else "未执行"
    lines.append(f"  执行: {executed}")
    return "\n".join(lines)


def format_demo(records: list[dict], audit_display: str) -> str:
    body = [
        format_record(record, prefix=f"[{index}/{len(records)}] ")
        for index, record in enumerate(records, 1)
    ]
    chunks = ["退款演示：三拍", "", "\n\n".join(body), "", f"审计日志: {audit_display}", "回放命令: aag replay"]
    return "\n".join(chunks) + "\n"


def format_replay(records: list[dict]) -> str:
    if not records:
        return ""
    return "\n\n".join(format_record(record) for record in records) + "\n"


def _format_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
        return value
    return json.dumps(value, ensure_ascii=False)
