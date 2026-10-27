# 🐕 GuardDog MCP — AgentTradeGuard

> **Check if a token is SAFE before your AI agent trades it.** One call: `PASS / WARN / BLOCK` (BITE!).

MCP server for [AgentTradeGuard](https://guarddog.top) — agent-first token safety:
honeypot detection, contract audit, liquidity structure, **P95 23ms** verdicts.
Runs the same 4-source engine as the public API: **GoPlus + Etherscan V2 + DEX Screener + honeypot.is**, locally in your MCP client.

Source & issues: [github.com/guarddog-top/mcp-server-guarddog](https://github.com/guarddog-top/mcp-server-guarddog) · Prefer REST? [`api.guarddog.top/v1/check`](https://api.guarddog.top/v1/check)

```
You:  "check 0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82 on bsc before I buy"
Dog:  ✅ PASS — risk_score 0, no honeypot flags, pool healthy
      (or) 🦴 BLOCK: sell_tax 99%, pool age 2d, honeypot flagged — DO NOT TRADE
```

## Install — Claude Desktop / Cursor / any MCP client

```json
{
  "mcpServers": {
    "guarddog": {
      "command": "npx",
      "args": ["-y", "guarddog-mcp"]
    }
  }
}
```

First run prepares a shared Python env (~30–60s, needs **Python 3.10+**), after that every start is instant. No API key needed — free during beta.

## The one tool

```
check_address(chain, address, action="swap")
  chain:   "eth" | "bsc" | "solana" | "base"
  address: token contract / pool address (0x... or solana base58)
  action:  "swap" (default) | "approve"
```

Returns:

```json
{
  "risk_score": 97,
  "verdict": "BLOCK",
  "reasons": ["sell_tax 99%", "pool age 2d", "honeypot flagged"],
  "covered": false,
  "data_limited": false,
  "unknown_token": false
}
```

**Verdict semantics** (write this into your agent's trading flow):

| Verdict | Meaning | Agent should |
|---|---|---|
| `PASS` | safe to proceed | proceed |
| `WARN` | suspicious — read `reasons[]` | half-size entry or pass |
| `BLOCK` | honeypot / rug pattern | **do NOT trade** |
| `unknown_token=true` | no on-chain footprint | treat as WARN |
| `data_limited=true` | a source was down | treat with caution |

Call `check_address` **before every buy/approve**. A verdict after the trade is an autopsy, not a check.

## Prefer REST? (10-second version)

```bash
curl "https://api.guarddog.top/v1/check?chain=bsc&target=0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82"
```

Free beta: 50 checks/day/IP, no signup. Full spec: [guarddog.top/llms.txt](https://guarddog.top/llms.txt)

## Why GuardDog

- **4 live sources, fan-out parallel** — GoPlus (honeypot flags/taxes), Etherscan V2 (contract audit), DEX Screener (pool age/depth), honeypot.is (simulated buy-sell)
- **Validated**: ACM SolRPDS dataset, 116,304 labeled rug pulls, 100% coverage
- **Graceful degradation**: a source down → `data_limited` flag, never a hang, never a softened verdict
- **Agent-first errors**: every error message carries an executable hint
- **Chains**: ETH / BSC / Solana

## Requirements

- Node ≥ 18 (the `npx` launcher)
- Python ≥ 3.10 (the engine; macOS: `brew install python@3.12`, Ubuntu: `apt install python3.12`)

## Links

- Homepage: <https://guarddog.top>
- Full API spec: <https://guarddog.top/llms.txt>
- X: [@OnchainGuardDog](https://x.com/OnchainGuardDog) — daily on-chain threat feed 🐕

## License

MIT
