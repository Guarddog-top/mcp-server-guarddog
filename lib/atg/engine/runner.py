"""Parallel check runner (cache trio piece 2).
Fan-out: GoPlus + Etherscan + DEX Screener via asyncio.gather; per-source
timeout 8s; single-source failure degrades to data_limited (never blocks
aggregation, never softens/hardens verdict). GoPlus concurrency capped 3
(QPS). Cache short-circuit before any external call.
"""
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone

from atg.cache.redis_client import VerdictCache
from atg.engine.l1 import assess_l1
from atg.engine.l2 import assess_l2
from atg.engine.l3 import assess_l3
from atg.engine.verdict import aggregate
from atg.sources.base import SourceError, TokenUnknown
from atg.sources.dexscreener import DexScreenerClient
from atg.sources.etherscan import EtherscanClient
from atg.sources.goplus import GoplusClient, parse_token_security

GOPLUS_SEM = 3
SOURCE_TIMEOUT = 8.0
# 缓存命中也落库(cached=true)：调用量统计不漏计（增长官M1，默认开）
PERSIST_CACHE_HITS = os.environ.get("ATG_PERSIST_CACHE_HITS", "1") != "0"


class CheckRunner:
    def __init__(self, goplus=None, etherscan=None, dex=None, cache=None,
                 solana=None, repo=None, checker=None):
        self.goplus = goplus or GoplusClient()
        self.etherscan = etherscan or EtherscanClient()
        self.dex = dex or DexScreenerClient()
        self.cache = cache
        self.solana = solana
        self.repo = repo
        self.checker = checker  # None=禁用(不降级) | client=第4源
        self._sem = asyncio.Semaphore(GOPLUS_SEM)

    async def _goplus_guarded(self, chain, target):
        self._gp_was_unknown = False
        for attempt in range(2):  # 瞬时失败重试1次（CAKE案例）
            async with self._sem:
                try:
                    return await asyncio.wait_for(
                        self.goplus.token_security(chain, target),
                        SOURCE_TIMEOUT)
                except TokenUnknown:
                    self._gp_was_unknown = True
                    return None  # 合法回答：无记录
                except Exception:
                    if attempt:
                        raise
            await asyncio.sleep(0.5)

    async def check(self, chain, target, action="swap", amount=None,
                    agent_id=None, source=None) -> dict:
        t_start = asyncio.get_event_loop().time()
        if self.cache is not None:
            try:
                cached = await self.cache.get(chain, target, action)
            except Exception:
                cached = None  # Redis挂=裸跑，不让缓存层杀掉API
            if cached is not None:
                if PERSIST_CACHE_HITS:
                    await self._persist(chain, target, action, cached,
                                        asyncio.get_event_loop().time() - t_start,
                                        agent_id, source, cached=True)
                return cached
        if chain == "solana":
            return await self._check_solana(chain, target, action,
                                           amount, agent_id, source)
        self._dx_was_empty = False
        gp_task = self._goplus_guarded(chain, target)
        es_task = self._safe(self.etherscan.get_source_code(chain, target))
        dx_task = self._dx_guarded(chain, target)
        ck_task = self._safe(self.checker.check(chain, target)) \
            if self.checker is not None else _noop_none()
        gp, es, dx, ck = await asyncio.gather(
            self._safe_inner(gp_task), es_task, dx_task, ck_task,
            return_exceptions=False)
        data_limited = False
        unknown_token = False
        findings = []
        if isinstance(gp, TokenUnknown):
            # 源健康但无名：合法回答（v0.4语义分离，不算data_limited）
            gp = None
        if gp is None and self._gp_was_unknown:
            unknown_token = True
            gp = _neutral_goplus()
        elif gp is None:
            data_limited = True
            gp = _neutral_goplus()
        if es is None:
            data_limited = True
            es = dict(verified=True, contract_name="", proxy=False,
                      compiler="")  # 数据缺失=中性
        if dx is not None:
            findings += _dex_findings(dx)
        elif not self._dx_was_empty:
            data_limited = True  # dex请求失败(非健康空)才算缺失
        if self.checker is not None:
            if ck is None:
                data_limited = True  # 裁决：checker挂=data_limited不拖垮主链
            else:
                findings += _checker_findings(chain, ck)
        if unknown_token and (dx is not None or not self._dx_was_empty):
            unknown_token = False  # dex有池=代币存在；dex源挂=无法确认，都非unknown
        if unknown_token:
            from atg.engine.findings import Finding, SEV_WARN, tag
            findings.append(Finding(
                "l0_unknown", SEV_WARN,
                "无任何链上足迹（GoPlus与DEX均无记录，未知代币）",
                tag("l0")))
        findings += assess_l1(chain, gp, es)
        findings += assess_l2(gp)
        findings += assess_l3(gp)
        v = aggregate(findings, data_limited=data_limited)
        payload = dict(
            risk_score=v.risk_score, verdict=v.verdict,
            reasons=list(v.reasons), covered=v.covered,
            data_limited=v.data_limited, unknown_token=unknown_token,
            checked_at=datetime.now(timezone.utc).isoformat(),
            snapshot_hash=_snap(chain, target, action, v),
        )
        payload["_findings"] = [
            dict(code=f.code, severity=f.severity, reason=f.reason,
                 rule=f.rule) for f in findings]
        if self.cache is not None:
            try:
                slim = dict((k, x) for k, x in payload.items()
                            if k != "_findings")
                await self.cache.put(chain, target, action, slim, v.verdict)
            except Exception:
                pass  # 缓存写失败不影响响应
        await self._persist(chain, target, action, payload,
                            asyncio.get_event_loop().time() - t_start,
                            agent_id, source)
        payload.pop("_findings", None)  # API响应不带结构化findings
        return payload

    async def _dx_guarded(self, chain, target):
        """DEX：失败抛->safe层转None并标记非空因；健康无池返回None+empty标记。"""
        try:
            out = await asyncio.wait_for(
                self.dex.best_pair(chain, target), SOURCE_TIMEOUT)
            if out is None:
                self._dx_was_empty = True
            return out
        except Exception:
            return None

    async def _persist(self, chain, target, action, payload, elapsed,
                       agent_id, source=None, cached=False):
        """落库：失败绝不阻塞响应（T4b合同）。source=api|mcp|xbot 归因。"""
        if self.repo is None:
            return
        try:
            await self.repo.record(
                chain=chain, target=target, action=action,
                verdict=payload["verdict"],
                risk_score=payload["risk_score"],
                reasons=payload["reasons"], covered=payload["covered"],
                data_limited=payload.get("data_limited", False),
                snapshot_hash=payload["snapshot_hash"],
                agent_id=agent_id, latency_ms=round(elapsed * 1000, 1),
                findings=payload.get("_findings"),
                source=source, cached=cached)
        except Exception as e:
            import logging
            logging.getLogger("atg.persist").warning(
                "落库失败(降级不阻塞): %s", str(e)[:120])  # 留痕不抛

    async def _safe(self, coro):
        try:
            return await asyncio.wait_for(coro, SOURCE_TIMEOUT)
        except (SourceError, asyncio.TimeoutError, Exception):
            return None

    async def _safe_inner(self, task):
        try:
            return await task
        except (SourceError, asyncio.TimeoutError, Exception):
            return None



    async def _check_solana(self, chain, target, action, amount,
                             agent_id=None, source=None):
        """Solana简化路径（T1e边界：最高WARN永不BLOCK）。
        数据源=公共RPC(mint/freeze权限)+DEX Screener(池龄/深度)。"""
        t_start = asyncio.get_event_loop().time()
        from atg.engine.findings import Finding, SEV_WARN, tag
        if self.solana is None:
            from atg.sources.solana_rpc import SolanaRpcClient
            self.solana = SolanaRpcClient()
        data_limited = False
        findings = []
        info = None
        for attempt in range(2):  # 公共RPC抖动：重试1次
            try:
                info = await asyncio.wait_for(
                    self.solana.get_mint_info(target), SOURCE_TIMEOUT)
                break
            except Exception:
                if attempt == 0:
                    await asyncio.sleep(0.5)
                else:
                    data_limited = True
        if info is None:
            if not data_limited:
                pass  # 账户不存在：不改变结论（可能是池地址等）
        else:
            if info["mint_authority_retained"]:
                findings.append(Finding(
                    "sol_mint_auth", SEV_WARN,
                    "mint authority未放弃（可增发）", tag("sol")))
            if info["freeze_authority_retained"]:
                findings.append(Finding(
                    "sol_freeze_auth", SEV_WARN,
                    "freeze authority未放弃（可冻结资产）", tag("sol")))
        try:
            dx = await asyncio.wait_for(
                self.dex.best_pair("solana", target), SOURCE_TIMEOUT)
        except Exception:
            dx = None
            data_limited = True
        if dx is not None:
            findings += _dex_findings(dx)
        v = aggregate(findings, data_limited=data_limited)
        payload = dict(
            risk_score=v.risk_score, verdict=v.verdict,
            reasons=list(v.reasons), covered=v.covered,
            data_limited=v.data_limited, unknown_token=False,
            checked_at=datetime.now(timezone.utc).isoformat(),
            snapshot_hash=_snap(chain, target, action, v),
        )
        payload["_findings"] = [
            dict(code=f.code, severity=f.severity, reason=f.reason,
                 rule=f.rule) for f in findings]
        if self.cache is not None:
            try:
                slim = dict((k, x) for k, x in payload.items()
                            if k != "_findings")
                await self.cache.put(chain, target, action, slim, v.verdict)
            except Exception:
                pass
        await self._persist(chain, target, action, payload,
                            asyncio.get_event_loop().time() - t_start,
                            agent_id, source)
        payload.pop("_findings", None)
        return payload


async def _noop_none():
    """checker未启用时的占位协程（gather对齐用）。"""
    return None


def _checker_findings(chain, ck):
    """第4源规则：模拟买卖实测。is_honeypot=BLOCK级；实测卖税超阈=BLOCK级。"""
    from atg.engine.findings import Finding, SEV_BLOCK, tag
    from atg.engine.l1 import SELL_TAX_BLOCK
    fs = []
    if ck.get("is_honeypot") is True:
        fs.append(Finding("l1_checker_hp", SEV_BLOCK,
                          "honeypot.is模拟检测：买进后无法卖出（实测模拟失败）",
                          tag("l1")))
    st = ck.get("sell_tax")
    if st is not None and chain in SELL_TAX_BLOCK and st >= SELL_TAX_BLOCK[chain] * 100:
        fs.append(Finding("l1_checker_tax", SEV_BLOCK,
                          "模拟实测卖出税 %.0f%%≥阈值 %.0f%%（honeypot.is实测）"
                          % (st, SELL_TAX_BLOCK[chain] * 100), tag("l1")))
    return fs


def _neutral_goplus():
    gp = dict()
    for k in ("is_honeypot", "is_open_source", "is_proxy", "is_mintable",
              "hidden_owner", "selfdestruct", "transfer_pausable",
              "is_in_dex", "is_blacklisted", "is_whitelisted",
              "external_call", "cannot_buy", "slippage_modifiable",
              "personal_slippage_modifiable", "anti_whale_modifiable",
              "can_take_back_ownership", "trading_cooldown", "trust_list"):
        gp[k] = False
    gp["is_in_dex"] = None  # 数据缺失：不是False
    for k in ("buy_tax", "sell_tax", "transfer_tax"):
        gp[k] = None
    gp["creator_address"] = None
    gp["token_name"] = gp["token_symbol"] = None
    gp["honeypot_with_same_creator"] = 0
    gp["holder_count"] = None
    return gp


def _dex_findings(dx):
    from atg.engine.findings import Finding, SEV_WARN, tag
    fs = []
    if dx.get("pool_age_days") is not None and dx["pool_age_days"] < 7:
        fs.append(Finding("l3_pool_age", SEV_WARN,
                          "池龄 %.1f 天（<7天新盘）" % dx["pool_age_days"],
                          tag("l3")))
    if dx.get("liquidity_usd") is not None and dx["liquidity_usd"] < 10000:
        fs.append(Finding("l3_thin_pool", SEV_WARN,
                          "池深 $%.0f（<$10k 极浅）" % dx["liquidity_usd"],
                          tag("l3")))
    return fs


def _snap(chain, target, action, v):
    payload = dict(chain=chain, target=target.lower(), action=action,
                   verdict=v.verdict, score=v.risk_score,
                   reasons=list(v.reasons))
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False)
        .encode("utf-8")).hexdigest()