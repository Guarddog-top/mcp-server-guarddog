"""X bot 双格式回复（Agent-First #5：人读上两行，agent抄末行json）。"""
import json

EMOJI = dict(PASS="[OK]", WARN="[!]", BLOCK="BITE!")


def format_reply(payload: dict, symbol: str = "", chain: str = "") -> str:
    """payload=/v1/check返回 -> X回复文本。
    例:
      [!] WARN $XXX (bsc)
      sell_tax=5% | pool_age=2d | liquidity=$67k
      {"verdict":"WARN","risk":12,"top_reason":"..."}
    """
    v = payload.get("verdict", "?")
    tag = EMOJI.get(v, v)
    head = "%s %s%s (%s)" % (tag, "$" + symbol if symbol else "",
                             "", chain) if symbol else "%s (%s)" % (tag, chain)
    # 从reasons提取人读摘要行
    reasons = payload.get("reasons") or []
    digest = " | ".join(reasons[:3]) if reasons else "clean"
    tail = json.dumps(dict(
        verdict=v,
        risk=payload.get("risk_score"),
        top_reason=reasons[0] if reasons else None,
        data_limited=payload.get("data_limited", False),
        unknown_token=payload.get("unknown_token", False)),
        ensure_ascii=False)
    return "%s\n%s\n%s" % (head, digest, tail)
