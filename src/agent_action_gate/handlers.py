# SPDX-License-Identifier: Apache-2.0
"""Side-effect stubs used by the demo and the eval suite.

These functions do not contact a payment service or a customer database.
"""

from __future__ import annotations


def refund_stub(params: dict) -> dict:
    return {
        "status": "refunded",
        "amount_cny": params["amount_cny"],
        "order_id": params["order_id"],
    }
