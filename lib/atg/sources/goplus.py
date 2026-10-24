"""GoPlus client (credential-free public API, verified 2026-10-14).
Path format: /token_security/[chainid]?contract_addresses=ADDR (plural param).
"""
import httpx

from atg.sources.base import SourceError, TokenUnknown, get_json

CHAIN_ID = dict(eth=1, bsc=56)  # solana has separate endpoint (M1: simplified via RPC)

BOOL_FIELDS = (
    "is_honeypot", "is_open_source", "is_proxy", "is_mintable",
    "hidden_owner", "selfdestruct", "transfer_pausable", "is_in_dex",
    "is_blacklisted", "is_whitelisted", "external_call", "cannot_buy",
    "slippage_modifiable", "personal_slippage_modifiable",
    "anti_whale_modifiable", "can_take_back_ownership", "trading_cooldown",
    "trust_list",
)  # is_in_dex 不在此列：三态处理（None=GoPlus未给值，禁止当False）
TAX_FIELDS = ("buy_tax", "sell_tax", "transfer_tax")
STR_FIELDS = ("creator_address", "token_name", "token_symbol")


def parse_token_security(payload: dict, address: str) -> dict:
    result = payload.get("result") or dict()
    inner = result.get(address.lower())
    if inner is None:
        if not result:
            raise TokenUnknown("goplus: no record of %s" % address)
        inner = list(result.values())[0]
    out = dict()
    for k in BOOL_FIELDS:
        out[k] = inner.get(k) == "1"
    for k in TAX_FIELDS:
        v = inner.get(k)
        out[k] = None if v in (None, "") else float(v)
    dex_raw = inner.get("is_in_dex")
    out["is_in_dex"] = None if dex_raw in (None, "") else (dex_raw == "1")
    for k in STR_FIELDS:
        out[k] = inner.get(k)
    hw = inner.get("honeypot_with_same_creator")
    out["honeypot_with_same_creator"] = int(hw) if hw not in (None, "") else 0
    hc = inner.get("holder_count")
    out["holder_count"] = int(hc) if hc not in (None, "") else None
    return out


class GoplusClient:
    def __init__(self, base_url="https://api.gopluslabs.io/api/v1",
                 client: httpx.AsyncClient | None = None):
        self.base_url = base_url
        self._client = client or httpx.AsyncClient()

    async def token_security(self, chain: str, address: str) -> dict:
        cid = CHAIN_ID.get(chain)
        if cid is None:
            raise SourceError("goplus: unsupported chain %s (M1: eth/bsc)" % chain)
        url = "%s/token_security/%d" % (self.base_url, cid)
        payload = await get_json(url, dict(contract_addresses=address), self._client)
        if payload.get("code") != 1:
            raise SourceError("goplus code=%s msg=%s"
                              % (payload.get("code"), payload.get("message")))
        return parse_token_security(payload, address)
