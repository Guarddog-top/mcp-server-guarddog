"""Verdict aggregation (WARN-bias policy unchanged).
data_limited: True when any L3 source was unavailable (e.g. DEX Screener
429/timeout) - verdict itself is NOT softened nor hardened by missing data
(review 2026-10-16: 数据缺失不许变成放行理由，也不许变成拦截理由).
"""
from dataclasses import dataclass, field
from atg.engine.findings import SEV_INFO, SEV_WARN, SEV_BLOCK


@dataclass(frozen=True)
class Verdict:
    risk_score: int
    verdict: str
    reasons: tuple
    covered: bool
    data_limited: bool = False


def aggregate(findings, data_limited=False):
    ordered = sorted(findings, key=lambda f: -f.severity)
    has_block = any(f.severity == SEV_BLOCK for f in ordered)
    n_warn = sum(1 for f in ordered if f.severity == SEV_WARN)
    n_info = sum(1 for f in ordered if f.severity == SEV_INFO)
    if has_block:
        score = min(100, 80 + 5 * n_warn)
        verdict = "BLOCK"
        covered = False
    else:
        score = min(85, 20 * n_warn + 5 * n_info)
        verdict = "WARN" if n_warn else "PASS"
        covered = True
    return Verdict(risk_score=score, verdict=verdict,
                   reasons=tuple(f.reason for f in ordered),
                   covered=covered, data_limited=data_limited)