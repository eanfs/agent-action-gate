# SPDX-License-Identifier: Apache-2.0
"""In-process reference implementation of an agent action gate."""

from agent_action_gate.gate import ActionGate
from agent_action_gate.policy import PolicyError

__version__ = "0.1.0"
__all__ = ["ActionGate", "PolicyError", "__version__"]
