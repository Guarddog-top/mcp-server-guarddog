"""Verdict-level Redis cache (cache trio piece 1).
Key: vc:{chain}:{target_lower}:{action}. TTL: PASS 600s / WARN 300s /
BLOCK 3600s (review 2026-10-20: riskier verdict cached longer).
Hit path must make zero external calls -> <50ms budget.
"""
import json
import time

import redis.asyncio as aioredis

from atg.config import SETTINGS

PASS_TTL = SETTINGS.cache_ttl_sec          # 600
WARN_TTL = SETTINGS.warn_ttl_sec           # 300
BLOCK_TTL = SETTINGS.block_ttl_sec         # 3600


def _key(chain, target, action):
    return "vc:%s:%s:%s" % (chain, target.lower(), action)


class VerdictCache:
    def __init__(self, url: str | None = None,
                 client: aioredis.Redis | None = None):
        self._r = client or aioredis.from_url(
            url or SETTINGS.redis_url, decode_responses=True)

    async def get(self, chain, target, action) -> dict | None:
        raw = await self._r.get(_key(chain, target, action))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    async def put(self, chain, target, action, payload: dict,
                  verdict: str) -> None:
        if verdict == "BLOCK":
            ttl = BLOCK_TTL
        elif verdict == "WARN":
            ttl = WARN_TTL
        else:
            ttl = PASS_TTL
        await self._r.set(_key(chain, target, action),
                          json.dumps(payload, ensure_ascii=False), ex=ttl)

    async def incr_day(self, key: str, expires_at: int) -> int:
        """匿名日额度计数（增长官M1·PlanB）：INCR，首次设置当日UTC末过期。"""
        n = await self._r.incr(key)
        if n == 1:
            await self._r.expire(key, max(expires_at - int(time.time()), 60))
        return n

    async def close(self):
        await self._r.aclose()