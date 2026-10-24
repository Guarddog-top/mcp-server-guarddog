"""ATG MCP Server (M2 核心交付): /v1/check 的 MCP 协议纯包装层。
四源引擎零改动（m1-candidate 冻结），本层只做协议转换。
SDK v2 (MCPServer, mcp>=2.3)。
运行: python -m atg.mcp_server.server  (stdio transport)
"""
from mcp.server.mcpserver import MCPServer

from atg.engine.runner import CheckRunner

RUNNER = CheckRunner()


async def init_runner() -> CheckRunner:
    """main()启动时调用：接repo（PG不可达=NullRepo降级）+cache（可选）。
    裁定2026-10-18：MCP跃点必须落库——军团主力走MCP，不落=丢90%流量统计。"""
    from atg.cache.redis_client import VerdictCache
    from atg.config import SETTINGS
    from atg.db.repo import make_repo
    RUNNER.repo = await make_repo(SETTINGS.database_url)
    try:
        c = VerdictCache()
        await c.get("__ping__", "__ping__", "__ping__")
        RUNNER.cache = c
    except Exception:
        RUNNER.cache = None  # Redis不可用=直连模式
    return RUNNER


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
        version="2.1.0",
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
        if chain not in ("eth", "bsc", "solana"):
            raise ValueError("unsupported chain: %s (eth|bsc|solana)" % chain)
        if action not in ("swap", "approve"):
            raise ValueError("unsupported action: %s (swap|approve)" % action)
        return await RUNNER.check(chain, address, action, source="mcp")

    server.add_tool(check_address, name="check_address",
                    title="ATG 风控检查",
                    description="下单/授权前查链上目标风险："
                                "蜜罐检测+合约审计+流动性结构，毫秒级三档判定")
    return server


def main():
    """MCP loop v2：统一 anyio 单 loop（根治跨loop InterfaceError）。

    旧版 asyncio.run(init_runner()) 让 asyncpg pool 绑死 loop A，
    server.run() 内部 anyio 另起 loop B -> 跨loop用pool被 _persist
    静默吞 -> MCP永不落库零日志（守门人20261019部署实锤）。
    现形：一个 anyio.run 里先 init 后 run_stdio_async，同生共死。
    """
    import logging
    import anyio
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 防URL(含apikey)入日志
    anyio.run(_amain)


async def _amain():
    await init_runner()
    server = build_server()
    await server.run_stdio_async()  # 与pool同一loop内运行


if __name__ == "__main__":
    main()