"""DEX Screener client (free, no key; ~300 req/min limit -> cache layer
mandatory at runner). 429/timeout raises SourceError -> runner sets
data_limited, verdict unchanged by missing data.
"""
import time
import httpx

from atg.sources.base import SourceError, get_json

BASE = "https://api.dexscreener.com/latest/dex/tokens"
CHAIN_MAP = dict(eth="ethereum", bsc="bsc", solana="solana")


def parse_best_pair(payload, chain):
    """Pick deepest pair on requested chain; None if no pairs."""
    pairs = payload.get("pairs") or []
    want = CHAIN_MAP.get(chain, chain)
    mine = [p for p in pairs if p.get("chainId") == want]
    if not mine:
        return None
    def liq(p):
        lq = p.get("liquidity") or dict()
        return float(lq.get("usd") or 0)
    best = max(mine, key=liq)
    lq = best.get("liquidity") or dict()
    created = best.get("pairCreatedAt")
    return dict(
        pair_address=best.get("pairAddress"),
        dex=best.get("dexId"),
        liquidity_usd=float(lq.get("usd") or 0),
        pool_age_days=(time.time() * 1000 - float(created)) / 86400000.0
        if created else None,
    )


class DexScreenerClient:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient()

    async def best_pair(self, chain: str, address: str) -> dict | None:
        url = "%s/%s" % (BASE, address)
        payload = await get_json(url, dict(), self._client)
        return parse_best_pair(payload, chain)