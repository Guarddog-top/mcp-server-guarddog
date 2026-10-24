"""honeypot.is checker client (4th source, approved 2026-11-03).
Simulation-based detection (buy-sell roundtrip) — catches live honeypots
GoPlus has not indexed. Failure -> SourceError -> runner data_limited
(never blocks the main path, per ruling).
"""
import httpx

from atg.sources.base import SourceError, get_json

BASE = "https://api.honeypot.is/v2/IsHoneypot"
CHAIN_ID = dict(eth=1, bsc=56)  # solana不支持（官方仅EVM）


def parse_checker(payload: dict) -> dict:
    """-> is_honeypot bool | None / sell_tax / buy_tax（百分数制0-100）。"""
    hp = (payload.get("honeypotResult") or dict()).get("isHoneypot")
    sim = payload.get("simulationResult") or dict()
    def fnum(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return dict(
        is_honeypot=None if hp is None else bool(hp),
        sell_tax=fnum(sim.get("sellTax")),
        buy_tax=fnum(sim.get("buyTax")),
    )


class HoneypotIsClient:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient()

    async def check(self, chain: str, address: str) -> dict:
        cid = CHAIN_ID.get(chain)
        if cid is None:
            raise SourceError("honeypot.is: unsupported chain %s" % chain)
        payload = await get_json(BASE, dict(chainID=str(cid),
                                             address=address),
                                  self._client, timeout=12.0)
        return parse_checker(payload)