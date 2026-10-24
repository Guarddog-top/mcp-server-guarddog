"""Etherscan V2 client (one key all chains; V1 deprecated 2026-10 verified).
Free tier: contract module all chains OK; account module (txlist) ETH only.
"""
import httpx

from atg.config import SETTINGS
from atg.sources.base import SourceError, get_json

CHAIN_ID = dict(eth=1, bsc=56)
BASE = "https://api.etherscan.io/v2/api"


def parse_source_code(payload: dict) -> dict:
    if str(payload.get("status")) != "1" or not isinstance(payload.get("result"), list):
        msg = payload.get("message", "?")
        raise SourceError("etherscan getsourcecode failed: %s" % msg)
    r = payload["result"][0]
    return dict(
        verified=bool(r.get("SourceCode")),
        contract_name=r.get("ContractName", ""),
        proxy=r.get("Proxy") == "1",
        compiler=r.get("CompilerVersion", ""),
    )


class EtherscanClient:
    def __init__(self, api_key: str | None = None,
                 client: httpx.AsyncClient | None = None):
        self._key = api_key or SETTINGS.etherscan_api_key
        self._client = client or httpx.AsyncClient()

    async def _call(self, chainid: int, module: str, action: str, **extra) -> dict:
        params = dict(chainid=str(chainid), module=module, action=action,
                      apikey=self._key)
        params.update(extra)
        return await get_json(BASE, params, self._client)

    async def get_source_code(self, chain: str, address: str) -> dict:
        cid = CHAIN_ID.get(chain)
        if cid is None:
            raise SourceError("etherscan: unsupported chain %s" % chain)
        payload = await self._call(cid, "contract", "getsourcecode", address=address)
        return parse_source_code(payload)

    async def creator_txs(self, chain: str, address: str) -> list:
        """Deployer history (L2). Free tier = ETH only; BSC needs paid plan."""
        if chain != "eth":
            raise SourceError(
                "etherscan account module is ETH-only on free tier "
                "(BSC via GoPlus rug_pull per approved motion)")
        payload = await self._call(1, "account", "txlist",
                                   address=address, page="1", offset="50",
                                   sort="asc")
        if str(payload.get("status")) != "1" or not isinstance(payload.get("result"), list):
            raise SourceError("etherscan txlist failed: %s" % payload.get("message"))
        return payload["result"]
