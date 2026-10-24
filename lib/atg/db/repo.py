"""PostgreSQL verdict snapshot store (T4b; label-library seed for M2).
Contract (review 2026-10-25): record() failures NEVER block /v1/check;
agent_id + latency_ms reserved for M3 billing/observability.
NullRepo used when PG unreachable - API degrades to no-persist mode.
"""
import json
from datetime import datetime, timezone

import asyncpg

DDL = """
CREATE TABLE IF NOT EXISTS detection_results (
    id BIGSERIAL PRIMARY KEY,
    chain TEXT NOT NULL,
    target TEXT NOT NULL,
    action TEXT NOT NULL,
    verdict TEXT NOT NULL,
    risk_score INT NOT NULL,
    reasons JSONB NOT NULL,
    findings JSONB,
    covered BOOLEAN NOT NULL,
    data_limited BOOLEAN NOT NULL DEFAULT FALSE,
    snapshot_hash TEXT NOT NULL,
    agent_id TEXT,
    latency_ms REAL,
    source TEXT,
    cached BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 存量部署在线迁移（2026-10-23 增长官埋点：source 归因 + cached 计数）
ALTER TABLE detection_results ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE detection_results
    ADD COLUMN IF NOT EXISTS cached BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_results_target
    ON detection_results (chain, target);
CREATE INDEX IF NOT EXISTS idx_results_created
    ON detection_results (created_at);
CREATE INDEX IF NOT EXISTS idx_results_agent
    ON detection_results (agent_id, created_at);
CREATE TABLE IF NOT EXISTS address_labels (
    id BIGSERIAL PRIMARY KEY,
    chain TEXT NOT NULL,
    address TEXT NOT NULL,
    label TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chain, address, label, source)
);
-- X 帖 -> guarddog.top 引流埋点（/t.gif 像素，增长官 2026-10-23）
CREATE TABLE IF NOT EXISTS traffic_events (
    id BIGSERIAL PRIMARY KEY,
    utm_source TEXT,
    utm_campaign TEXT,
    utm_content TEXT,
    referer TEXT,
    ua TEXT,
    ip_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_traffic_created
    ON traffic_events (created_at);
"""


class NullRepo:
    """PG不可用时的空实现：接口一致，静默丢弃。"""
    async def initialize(self):
        return self

    async def record(self, **kw):
        return None

    async def record_event(self, **kw):
        return None

    async def close(self):
        return None

    async def stats(self, days=7):
        return {}


class ResultsRepo:
    def __init__(self, dsn: str, pool=None):
        self._dsn = dsn
        self._pool = pool

    async def initialize(self):
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn,
                                                   min_size=1, max_size=4)
        async with self._pool.acquire() as conn:
            await conn.execute(DDL)
        return self

    async def record(self, chain, target, action, verdict, risk_score,
                     reasons, covered, data_limited, snapshot_hash,
                     agent_id=None, latency_ms=None, findings=None,
                     source=None, cached=False):
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO detection_results (chain, target, action, "
                "verdict, risk_score, reasons, findings, covered, "
                "data_limited, snapshot_hash, agent_id, latency_ms, "
                "source, cached) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)",
                chain, target.lower(), action, verdict, risk_score,
                json.dumps(reasons, ensure_ascii=False),
                json.dumps(findings, ensure_ascii=False) if findings else None,
                covered, data_limited, snapshot_hash, agent_id, latency_ms,
                source, cached)

    async def record_event(self, utm_source=None, utm_campaign=None,
                           utm_content=None, referer=None, ua=None,
                           ip_hash=None):
        """引流像素事件（/t.gif）。失败静默——埋点永不影响业务。"""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO traffic_events (utm_source, utm_campaign, "
                "utm_content, referer, ua, ip_hash) "
                "VALUES ($1,$2,$3,$4,$5,$6)",
                utm_source, utm_campaign, utm_content, referer, ua, ip_hash)

    async def stats(self, days=7):
        """增长漏斗一站式统计（增长官 M1）：调用量/链分布/verdict/
        source 归因/留存sets/延迟/引流事件。单查询轻聚合，beta 规模直查。"""
        async with self._pool.acquire() as conn:
            daily = await conn.fetch(
                "SELECT date_trunc('day', created_at) AS d, count(*) AS n, "
                "count(DISTINCT agent_id) AS agents, "
                "count(*) FILTER (WHERE cached) AS cached_n "
                "FROM detection_results "
                "WHERE created_at > now() - ($1 || ' days')::interval "
                "GROUP BY d ORDER BY d", str(days))
            chains = await conn.fetch(
                "SELECT chain, count(*) AS n FROM detection_results "
                "WHERE created_at > now() - ($1 || ' days')::interval "
                "GROUP BY chain", str(days))
            verdicts = await conn.fetch(
                "SELECT verdict, count(*) AS n FROM detection_results "
                "WHERE created_at > now() - ($1 || ' days')::interval "
                "GROUP BY verdict", str(days))
            sources = await conn.fetch(
                "SELECT coalesce(source, 'unknown') AS src, count(*) AS n "
                "FROM detection_results "
                "WHERE created_at > now() - ($1 || ' days')::interval "
                "GROUP BY src", str(days))
            lat = await conn.fetchrow(
                "SELECT round(avg(latency_ms)::numeric, 1) AS avg_ms, "
                "round(percentile_cont(0.95) "
                "WITHIN GROUP (ORDER BY latency_ms)::numeric, 1) AS p95_ms "
                "FROM detection_results "
                "WHERE created_at > now() - ($1 || ' days')::interval "
                "AND latency_ms IS NOT NULL", str(days))
            agent_days = await conn.fetch(
                "SELECT date_trunc('day', created_at) AS d, "
                "array_agg(DISTINCT agent_id) AS agents "
                "FROM detection_results "
                "WHERE created_at > now() - ($1 || ' days')::interval "
                "AND agent_id IS NOT NULL GROUP BY d ORDER BY d", str(days))
            traffic = await conn.fetch(
                "SELECT utm_source, utm_campaign, count(*) AS n "
                "FROM traffic_events "
                "WHERE created_at > now() - ($1 || ' days')::interval "
                "GROUP BY utm_source, utm_campaign", str(days))
        # D1/D7 留存：当日活跃 agent 在随后 1/7 天内再次出现的比例
        sets = {(r["d"].date().isoformat()): set(r["agents"])
                for r in agent_days}
        dates = sorted(sets)
        for lag, key in ((1, "d1"), (7, "d7")):
            retained, base = 0, 0
            for i, d in enumerate(dates):
                if i + lag >= len(dates):
                    continue
                nxt = set().union(*(sets[dates[j]]
                                    for j in range(i + 1,
                                                   min(i + lag + 1,
                                                       len(dates)))))
                base += len(sets[d])
                retained += len(sets[d] & nxt)
            sets[f"__{key}"] = round(retained / base, 4) if base else None
        retention = {k: sets.pop(f"__{k}") for k in ("d1", "d7")
                     if f"__{k}" in sets}
        return dict(
            daily=[dict(date=r["d"].date().isoformat(), checks=r["n"],
                        unique_agents=r["agents"], cached=r["cached_n"])
                   for r in daily],
            chains={r["chain"]: r["n"] for r in chains},
            verdicts={r["verdict"]: r["n"] for r in verdicts},
            sources={r["src"]: r["n"] for r in sources},
            latency=dict(avg_ms=float(lat["avg_ms"]) if lat["avg_ms"] else None,
                         p95_ms=float(lat["p95_ms"]) if lat["p95_ms"] else None),
            agent_daily={d: len(s) for d, s in sets.items()},
            retention=retention,
            traffic=[dict(utm_source=r["utm_source"],
                          utm_campaign=r["utm_campaign"], n=r["n"])
                     for r in traffic])

    async def add_label(self, chain, address, label, source="engine"):
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO address_labels (chain, address, label, source) "
                "VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                chain, address.lower(), label, source)

    async def close(self):
        if self._pool is not None:
            await self._pool.close()


async def make_repo(dsn: str | None):
    """PG可达→ResultsRepo；不可达→NullRepo（不阻塞API）。"""
    if not dsn:
        return NullRepo()
    try:
        return await ResultsRepo(dsn).initialize()
    except Exception:
        return NullRepo()