"""ATG MCP Server v1.0.1: cloud-API backed thin client (stdio transport).

v1.0.0 在用户本地跑整套引擎(需PG/Redis/Etherscan key, venv 60s, 使用零遥测)。
v1.0.1 改为直连 api.guarddog.top/v1/check —— 同一套四源引擎, 服务端落库:
- venv 只需 mcp+httpx (~10s), 无本地数据库/密钥要求
- MCP 流量经 beta token 归因为独立 agent_id, 使用量首次可测
- 裁定对齐 2026-10-18: MCP跃点必须落库。本地引擎=军团流量黑洞。

运行: python -m atg.mcp_server.server

v1.0.4 (2026-11-07 验收回炉版, 基座=1.0.1 云端瘦客户端):
- 补齐 MCP 标准工具元数据 ToolAnnotations(readOnly/destructive/idempotent/openWorld)
  —— M8ven Trust Index 独立审计扣分项, 所有 MCP 目录通用加分
- 链表扩为 eth|bsc|solana|base|arc: base 对齐 2026-10-27 四链裁决;
  arc(Circle Agent L1)为框架级支持 —— 检测源接入前返回 covered=false, 不虚标检测力
- 教训存档: 1.0.2/1.0.3 曾从 M2 旧基座打包(本地引擎+全栈venv), 系 repo 分裂所致。
  发版纪律: npm pack 解包后 grep readOnlyHint/cloud BASE/--smoke 三证齐全才许 publish。
"""
import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

BASE = "https://api.guarddog.top/v1/check"
BETA_TOKEN = "free-during-beta"  # AGENTS.md 公开的 beta 免费token
UA = "guarddog-mcp/1.0.4"
CHAINS = ("eth", "bsc", "solana", "base", "arc")
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
        version="1.0.4",
    )

    async def check_address(chain: str, address: str,
                            action: str = "swap") -> dict:
        """Check if a token is SAFE to trade BEFORE your agent buys it.

        Call before every buy/approve. Returns verdict PASS (proceed),
        WARN (read reasons[] then decide), or BLOCK (do NOT trade -
        honeypot/scam detected).

        Args:
            chain: 'eth' | 'bsc' | 'solana' | 'base' | 'arc'
                (arc = Circle Agent L1, framework-level support:
                 detection sources not yet integrated, returns covered=false)
            address: token contract address (0x... or solana base58)
            action: what your agent is about to do: 'swap' | 'approve'

        Returns:
            verdict, risk_score (0-100), reasons[] (human-readable),
            covered (insurance eligibility), data_limited, unknown_token
        """
        if chain not in CHAINS:
            raise ValueError(
                "unsupported chain: %s (eth|bsc|solana|base|arc)" % chain)
        if action not in ACTIONS:
            raise ValueError("unsupported action: %s (swap|approve)" % action)
        try:
            return await _cloud_check(chain, address, action)
        except RuntimeError as e:
            # arc: 云端检测源未接入(REST 缓行, MCP 先行) —— 优雅降级, 不虚标检测力
            # 注: 云端对非法链返回 422 invalid_chain(FastAPI 校验), 非 400
            if chain == "arc" and "invalid_chain" in str(e):
                return {
                    "chain": "arc",
                    "verdict": "UNKNOWN",
                    "covered": False,
                    "risk_score": None,
                    "reasons": [
                        "arc (Circle Agent L1) detection sources not yet "
                        "integrated — framework-level support only",
                        "treat any arc target as unverified until live "
                        "coverage lands",
                    ],
                    "note": "GuardDog is Arc-framework-ready; live detection "
                            "for arc is coming. This response is an explicit "
                            "not-covered signal, not a PASS.",
                }
            raise

    server.add_tool(check_address, name="check_address",
                    title="ATG 风控检查",
                    description="下单/授权前查链上目标风险："
                                "蜜罐检测+合约审计+流动性结构，毫秒级三档判定",
                    annotations=ToolAnnotations(
                        readOnlyHint=True,
                        destructiveHint=False,
                        idempotentHint=True,
                        openWorldHint=True))
    return server


def main():
    """MCP stdio loop. v1.0.1 起无本地资源需要预热, 直接起服务。"""
    import anyio

    async def _amain():
        await build_server().run_stdio_async()

    anyio.run(_amain)


if __name__ == "__main__":
    main()
