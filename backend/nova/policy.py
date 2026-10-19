"""Default-deny tool authorization; model output cannot grant permissions."""
from dataclasses import dataclass
from enum import StrEnum
class Risk(StrEnum):
    LOW="low"; MEDIUM="medium"; HIGH="high"; CRITICAL="critical"
@dataclass(frozen=True)
class Decision:
    allowed: bool
    requires_approval: bool
    reason: str
_TOOL_POLICY = {"calculator": (Risk.LOW, False), "text_stats": (Risk.LOW, False), "json_format": (Risk.LOW, False), "base64_encode": (Risk.LOW, False), "base64_decode": (Risk.LOW, False), "csv_summary": (Risk.LOW, False), "markdown_outline": (Risk.LOW, False), "workspace_read": (Risk.LOW, False), "knowledge_search": (Risk.LOW, False),
                "workspace_write": (Risk.MEDIUM, True), "rollback_snapshot": (Risk.HIGH, True), "agent_tool_execute": (Risk.MEDIUM, True),
                "sandbox_code": (Risk.HIGH, True),
                "delete": (Risk.CRITICAL, True)}
def evaluate_tool(name: str, approved: bool=False) -> Decision:
    policy = _TOOL_POLICY.get(name)
    if policy is None: return Decision(False, False, "Tool is not registered; default deny.")
    risk, required = policy
    if required and not approved: return Decision(False, True, f"{risk.value} risk action requires explicit approval.")
    return Decision(True, False, "Allowed by registered policy.")
