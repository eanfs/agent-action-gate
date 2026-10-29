# SPDX-License-Identifier: Apache-2.0
"""Approval hooks. The simulated approver never reads the environment."""

from __future__ import annotations

import sys

from agent_action_gate.render import format_params


class SimulatedApprover:
    """Non-interactive approver used by `aag demo refund` by default."""

    def decide(self, action: str, params: dict, reason: str) -> dict:
        del action, params, reason
        return {
            "outcome": "approved",
            "approver": "simulated-approver",
            "mode": "simulated",
        }


class InteractiveApprover:
    """Read a single y/N answer from stdin. The prompt goes to stderr."""

    def decide(self, action: str, params: dict, reason: str) -> dict:
        del reason
        prompt = f"审批 {action} {format_params(params)} ? [y/N]: "
        sys.stderr.write(prompt)
        sys.stderr.flush()
        answer = sys.stdin.readline().strip().lower()
        outcome = "approved" if answer in {"y", "yes"} else "denied"
        return {
            "outcome": outcome,
            "approver": "interactive-operator",
            "mode": "interactive",
        }


def resolve_approver(approver):
    if approver is None or approver == "none":
        return None
    if approver == "simulated":
        return SimulatedApprover()
    if approver == "interactive":
        return InteractiveApprover()
    if hasattr(approver, "decide"):
        return approver
    raise TypeError("approver 必须是 None、'simulated'、'interactive'，或带 decide 方法的对象")
