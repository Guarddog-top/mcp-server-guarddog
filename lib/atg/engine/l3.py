"""L3 liquidity structure rules.
M1 v0: GoPlus holders/is_in_dex (top-N concentration) + DEX Screener
age/depth wired at runner (client T1d). Solana boundary: simplified rules
never exceed WARN (plan section 1).
"""
from atg.engine.findings import Finding, SEV_WARN, tag

TOP3_HOLD_PCT_WARN = 0.80


def top_holder_concentration(holders, top_n=3):
    """top_n percent sum as fraction; locked holders excluded."""
    live = [h for h in (holders or []) if not h.get("is_locked")]
    live = sorted(live, key=lambda h: float(h.get("percent", 0)), reverse=True)
    return sum(float(h.get("percent", 0)) for h in live[:top_n])


def assess_l3(gp, holders=None):
    fs = []
    if gp.get("is_in_dex") is False:  # None=数据缺失不告警（data_limited语义）
        fs.append(Finding("l3_not_in_dex", SEV_WARN,
                          "代币未进任何DEX池（is_in_dex=0），无退出流动性", tag("l3")))
    hc = gp.get("holder_count")
    if hc and 0 < hc < 30:  # 0/None=数据缺失不触发
        fs.append(Finding("l3_few_holders", SEV_WARN,
                          "持有人仅 %d（<30），高度集中风险" % hc, tag("l3")))
    if holders:
        c = top_holder_concentration(holders)
        if c >= TOP3_HOLD_PCT_WARN:
            fs.append(Finding("l3_top3_conc", SEV_WARN,
                              "前3持有人占比 %.0f%%（≥80%%阈值）" % (c * 100), tag("l3")))
    return fs