"""Finding: one risk signal from a detection layer.
severity: SEV_INFO < SEV_WARN < SEV_BLOCK. reason carries field+threshold;
rule carries version tag (e.g. "v0.3-l1") for audit/hot-update traceability
(review requirement 2026-10-16).
"""
from dataclasses import dataclass

SEV_INFO = 10
SEV_WARN = 30
SEV_BLOCK = 100
RULE_VERSION = "v0.3"


@dataclass(frozen=True)
class Finding:
    code: str      # rule id, e.g. "l1_honeypot"
    severity: int
    reason: str
    rule: str = "" # "v0.3-l1" family tag


def tag(family):
    return RULE_VERSION + "-" + family
