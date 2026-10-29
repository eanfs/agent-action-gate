# SPDX-License-Identifier: Apache-2.0
"""Command line for the agent action gate."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from agent_action_gate import __version__
from agent_action_gate.audit import AuditError, AuditLog
from agent_action_gate.demo import run_refund_demo
from agent_action_gate.eval_suite import run_eval
from agent_action_gate.policy import PolicyError
from agent_action_gate.render import format_demo, format_replay

DEFAULT_AUDIT = ".aag/audit.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aag",
        description="Agent 动作闸门：类型、权限、审批、审计回放、评测门槛。",
    )
    parser.add_argument("--version", action="version", version=f"aag {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="运行内置演示")
    demo_sub = demo.add_subparsers(dest="scenario", required=True)
    refund = demo_sub.add_parser("refund", help="三拍退款演示")
    refund.add_argument(
        "--interactive",
        action="store_true",
        help="800 CNY 那一拍从标准输入读取 y/N；默认使用模拟审批人",
    )
    refund.add_argument("--audit", default=DEFAULT_AUDIT, help=f"审计日志路径（默认 {DEFAULT_AUDIT}）")

    replay = sub.add_parser("replay", help="回放审计日志")
    replay.add_argument("decision_id", nargs="?", help="只回放这一条，例如 dec_002")
    replay.add_argument("--audit", default=DEFAULT_AUDIT, help=f"审计日志路径（默认 {DEFAULT_AUDIT}）")

    evaluate = sub.add_parser("eval", help="跑内置评测，通过率低于阈值则退出码为 1")
    evaluate.add_argument("--threshold", type=float, default=1.0, help="通过率阈值，默认 1.0")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 2
    try:
        if args.command == "demo":
            return _demo(args)
        if args.command == "replay":
            return _replay(args)
        if args.command == "eval":
            return _eval(args)
    except (AuditError, PolicyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("未知命令", file=sys.stderr)
    return 2


def console_main() -> None:
    sys.exit(main())


def _demo(args) -> int:
    _check_audit_path(args.audit)
    records = run_refund_demo(args.audit, interactive=args.interactive)
    sys.stdout.write(format_demo(records, args.audit))
    return 0


def _replay(args) -> int:
    _check_audit_path(args.audit)
    log = AuditLog(args.audit)
    if log.path is not None and not Path(log.path).is_file():
        print(f"找不到审计日志: {log.path}", file=sys.stderr)
        return 2
    records = log.read()
    if args.decision_id:
        records = [record for record in records if record.get("id") == args.decision_id]
        if not records:
            print(f"找不到决策 {args.decision_id}", file=sys.stderr)
            return 2
    elif not records:
        print("审计日志是空的", file=sys.stderr)
        return 2
    sys.stdout.write(format_replay(records))
    return 0


def _eval(args) -> int:
    threshold = args.threshold
    if not math.isfinite(threshold) or threshold < 0:
        print("阈值必须是大于等于 0 的有限数字", file=sys.stderr)
        return 2
    text, code = run_eval(threshold)
    sys.stdout.write(text)
    return code


def _check_audit_path(path: str) -> None:
    if not isinstance(path, str) or path.strip() != path or "\n" in path or "\x00" in path or path == "":
        raise AuditError("审计路径无效")
