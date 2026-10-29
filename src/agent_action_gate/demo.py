# SPDX-License-Identifier: Apache-2.0
"""Three-beat refund demo."""

from __future__ import annotations

from agent_action_gate.gate import ActionGate
from agent_action_gate.handlers import refund_stub

DEMO_ACTOR = "refund-demo-agent"
DEMO_MODEL = "demo"

DEMO_CALLS = (
    (
        "refund",
        {"amount_cny": 50, "order_id": "ord_1001", "reason": "duplicate_charge"},
    ),
    (
        "refund",
        {"amount_cny": 800, "order_id": "ord_1002", "reason": "goodwill"},
    ),
    (
        "delete_customer",
        {"customer_id": "cus_42"},
    ),
)


def run_refund_demo(audit_path: str = ".aag/audit.jsonl", *, interactive: bool = False) -> list[dict]:
    approver = "interactive" if interactive else "simulated"
    gate = ActionGate.open(audit_path=audit_path, approver=approver)
    gate.register("refund", refund_stub)
    gate.reset_audit()
    records = []
    for action, params in DEMO_CALLS:
        records.append(gate.call(action, params, actor=DEMO_ACTOR, model=DEMO_MODEL))
    return records
