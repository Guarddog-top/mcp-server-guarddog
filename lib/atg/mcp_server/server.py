"""ATG MCP Server v1.0.1: cloud-API backed thin client (stdio transport).

v1.0.0 在用户本地跑整套引擎(需PG/Redis/Etherscan key, venv 60s, 使用零遥测)。
v1.0.1 改为直连 api.guarddog.top/v1/check —— 同一套四源引擎, 服务端落库:
- venv 只需 mcp+httpx (~10s), 无本地数据库/密钥要求
- MCP 流量经 beta token 归因为独立 agent_id, 使用量首次可测
- 裁定对齐 2026-10-18: MCP跃点必须落库。本地引擎=军团流量黑洞。

运行: python -m atg.mcp_server.server
"""
import httpx
from mcp.server.mcpserver import MCPServer

BASE = "https://api.guarddog.top/v1/check"
BETA_TOKEN = "free-during-beta"  # AGENTS.md 公开的 beta 免费token
UA = "guarddog-mcp/1.0.1"
CHAINS = ("eth", "bsc", "solana")
ACTIONS = ("swap", "approve")


async def _cloud_check(chain: str, address: str, action: str) -> dict:
    params = {"chain": chain, "target": address, "action": action}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(BASE, params=params,
                        headers={"User-Agent": UA, "X-GuardDog-Token": BETA_TOKEN})
        if r.status_code in (401, 403):  # beta token 被拒 → 匿名重试(50/天/IP)
            r = await c.get(BASE, params=params, headers={"User-Agent": UA})
    if r.status_code >= 400:
        try:
            err = r.json()
            raise RuntimeError(
                f"guarddog api {r.status_code}: {err.get('error', '?')} "
                f"— hint: {err.get('hint', '-')}")
        except ValueError:
            raise RuntimeError(f"guarddog api {r.status_code}: {r.text[:120]}")
    return r.json()


def build_server() -> MCPServer:
    server = MCPServer(
        name="agenttradeguard",
        title="AgentTradeGuard",
        description="Check if a token is SAFE to trade BEFORE your agent "
                    "buys it. Returns PASS/WARN/BLOCK with reasons. "
                    "Call this before every trade.",
        instructions="Call check_address before every buy/approve. "
                     "BLOCK = do NOT trade (honeypot/scam pattern detected). "
                     "WARN = read reasons[] then decide. "
                     "PASS = safe to proceed. "
                     "data_limited=true means partial data; "
                     "unknown_token=true means no on-chain footprint.",
        version="1.0.1",
    )

    async def check_address(chain: str, address: str,
                            action: str = "swap") -> dict:
        """Check if a token is SAFE to trade BEFORE your agent buys it.

        Call before every buy/approve. Returns verdict PASS (proceed),
        WARN (read reasons[] then decide), or BLOCK (do NOT trade -
        honeypot/scam detected).

        Args:
            chain: the chain the token is on: 'eth' | 'bsc' | 'solana'
            address: token contract address (0x... or solana base58)
            action: what your agent is about to do: 'swap' | 'approve'

        Returns:
            verdict, risk_score (0-100), reasons[] (human-readable),
            covered (insurance eligibility), data_limited, unknown_token
        """
        if chain not in CHAINS:
            raise ValueError("unsupported chain: %s (eth|bsc|solana)" % chain)
        if action not in ACTIONS:
            raise ValueError("unsupported action: %s (swap|approve)" % action)
        return await _cloud_check(chain, address, action)

    server.add_tool(check_address, name="check_address",
                    title="ATG 风控检查",
                    description="下单/授权前查链上目标风险："
                                "蜜罐检测+合约审计+流动性结构，毫秒级三档判定")
    return server


def main():
    """MCP stdio loop. v1.0.1 起无本地资源需要预热, 直接起服务。"""
    import anyio

    async def _amain():
        await build_server().run_stdio_async()

    anyio.run(_amain)


if __name__ == "__main__":
    main()
