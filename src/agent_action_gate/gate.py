# SPDX-License-Identifier: Apache-2.0
"""In-process action gate: authorize, optionally approve, execute, audit."""

from __future__ import annotations

import copy
import json

from agent_action_gate.approvers import resolve_approver
from agent_action_gate.audit import AuditLog
from agent_action_gate.policy import Policy, load_policy


class ActionGate:
    def __init__(self, policy: Policy, audit_path: str | None = ".aag/audit.jsonl", approver=None):
        self.policy = policy
        self.audit = AuditLog(audit_path)
        self.approver = resolve_approver(approver)
        self._handlers: dict = {}

    @classmethod
    def open(cls, policy_path: str | None = None, audit_path: str | None = ".aag/audit.jsonl", approver=None):
        return cls(load_policy(policy_path), audit_path=audit_path, approver=approver)

    def register(self, action: str, handler) -> "ActionGate":
        if not callable(handler):
            raise TypeError("handler 必须可调用")
        self._handlers[action] = handler
        return self

    def reset_audit(self) -> None:
        self.audit.reset()

    def call(self, action, params, *, actor: str = "agent", model: str = "unspecified") -> dict:
        decision = self.policy.authorize(action, params)
        stored_params = _bounded_params(params)
        approval = None
        executed = False
        output = None
        if decision["decision"] == "allow":
            executed, output = self._invoke(action, params)
        elif decision["decision"] == "require_approval" and self.approver is not None:
            approval = _normalize_approval(self.approver.decide(str(action), stored_params, decision["reason"]))
            if approval["outcome"] == "approved":
                executed, output = self._invoke(action, params)
        record = {
            "actor": _label(actor, "agent"),
            "model": _label(model, "unspecified"),
            "action": action if isinstance(action, str) else "<invalid>",
            "params": stored_params,
            "policy_version": self.policy.version,
            "decision": decision["decision"],
            "rule": decision["rule"],
            "reason": decision["reason"],
            "reversible": decision["reversible"],
            "idempotency_key": decision["idempotency_key"],
            "approval": approval,
            "executed": executed,
            "output": output,
        }
        return self.audit.append(record)

    def _invoke(self, action, params) -> tuple[bool, dict | None]:
        handler = self._handlers.get(action)
        if handler is None:
            return False, {"error": "no_handler"}
        try:
            output = handler(copy.deepcopy(params) if isinstance(params, dict) else {})
        except Exception:
            return False, {"error": "handler_failed"}
        if not isinstance(output, dict):
            return False, {"error": "handler_output_not_object"}
        try:
            encoded = json.dumps(output, ensure_ascii=False)
        except (TypeError, ValueError):
            return False, {"error": "handler_output_not_json"}
        if len(encoded) > 4000:
            return False, {"error": "handler_output_too_large"}
        return True, json.loads(encoded)


def _bounded_params(params) -> dict:
    if not isinstance(params, dict):
        return {"_invalid": True}
    try:
        encoded = json.dumps(params, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"_invalid": True}
    if len(encoded) > 4000:
        return {"_truncated": True}
    return json.loads(encoded)


def _normalize_approval(value) -> dict:
    if not isinstance(value, dict):
        return {"outcome": "denied", "approver": "invalid", "mode": "invalid"}
    outcome = value.get("outcome")
    if outcome not in {"approved", "denied"}:
        outcome = "denied"
    return {
        "outcome": outcome,
        "approver": _label(value.get("approver"), "invalid"),
        "mode": _label(value.get("mode"), "invalid"),
    }


def _label(value, default: str) -> str:
    if not isinstance(value, str):
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    return cleaned[:128]
