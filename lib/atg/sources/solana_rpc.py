"""Solana public RPC client (T1e, M1 simplified scope).
SPL Mint layout (82B): mintAuthorityOption u32@0, mintAuthority@4,
freezeAuthorityOption u32@46, freezeAuthority@50.
Boundary: findings from here max WARN, never BLOCK (plan section 1).
"""
import base64
import struct

import httpx

from atg.sources.base import SourceError, get_json

RPC_URL = "https://api.mainnet-beta.solana.com"


def parse_mint_account(raw: bytes) -> dict:
    if len(raw) < 82:
        raise SourceError("not an SPL mint account (len=%d)" % len(raw))
    m_opt = struct.unpack("<I", raw[0:4])[0]
    f_opt = struct.unpack("<I", raw[46:50])[0]
    return dict(mint_authority_retained=m_opt == 1,
                freeze_authority_retained=f_opt == 1)


class SolanaRpcClient:
    def __init__(self, url: str = RPC_URL,
                 client: httpx.AsyncClient | None = None):
        self.url = url
        self._client = client or httpx.AsyncClient()

    async def get_mint_info(self, address: str) -> dict | None:
        """None = account not found (closed/invalid)."""
        body = dict(jsonrpc="2.0", id=1, method="getAccountInfo",
                    params=[address, dict(encoding="base64")])
        import json as _j
        headers = dict()
        headers["Content-Type"] = "application/json"
        r = await self._client.post(self.url, content=_j.dumps(body),
                                    headers=headers, timeout=8.0)
        r.raise_for_status()
        d = r.json()
        val = ((d.get("result") or dict()).get("value"))
        if not val:
            return None
        arr = val.get("data") or []
        if not arr:
            return None
        return parse_mint_account(base64.b64decode(arr[0]))