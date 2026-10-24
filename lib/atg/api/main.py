"""ATG FastAPI app - /v1/check wired to real CheckRunner (D+14).
App factory pattern: deps injectable for tests; production defaults
read env (.env via docker). Mock mode kept behind ATG_MOCK=1 for
smoke without network.
"""
import hashlib
from pathlib import Path
import json
import os
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import Response

from atg import __version__
from atg.api.schemas import CheckResponse, HealthResponse

Chain = Literal["eth", "bsc", "solana"]

# 链名宽容归一（Agent-First第1条：消除一类错误的发生先于解释错误）
CHAIN_ALIASES = dict(sol="solana", bnb="bsc", bnbchain="bsc",
                     bnb_chain="bsc", bscchain="bsc",
                     ethereum="eth", ethmainnet="eth")


def normalize_chain(raw: str) -> str:
    return CHAIN_ALIASES.get(raw.strip().lower().replace(" ", "_"), raw)


# ── 增长官 M1 埋点层（2026-10-23）────────────────────────────
# 身份：匿名=sha256(IP)伪名（跨日稳定→可算留存）；token=sha256(token)
# 归因：source=api|xbot|web（HTTP头），mcp 由 mcp_server 直标
# 额度：匿名 ANON_DAILY_QUOTA 次/天（默认50，2026-10-23 终审 f64e23a）
#

def _anon_quota_limit() -> int:
    try:
        return int(os.environ.get("ANON_DAILY_QUOTA", "50"))
    except ValueError:
        return 50


def _client_ip(request: Request) -> str:
    ip = (request.headers.get("x-real-ip")
          or (request.headers.get("x-forwarded-for") or "").split(",")[0]
          or "").strip()
    return ip or (request.client.host if request.client else "unknown")


def _agent_id(request: Request) -> str:
    token = (request.headers.get("x-atg-token")
             or request.headers.get("x-guarddog-token") or "").strip()
    if token:
        return "tok:" + hashlib.sha256(token.encode()).hexdigest()[:16]
    return "anon:" + hashlib.sha256(
        _client_ip(request).encode()).hexdigest()[:16]


def _source_of(request: Request) -> str:
    src = (request.headers.get("x-atg-source") or "api").strip().lower()
    return src if src in ("api", "xbot", "web") else "api"


def _day_end_epoch() -> int:
    """当日 UTC 末（额度重置点）。"""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    return int((now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp())


async def _anon_quota_ok(app, request: Request):
    """匿名日额度。Redis 不可用=fail-open（beta 宽容，RUNBOOK 已注明）。"""
    cache = getattr(app.state, "cache", None)
    if cache is None:
        return True
    try:
        key = "anon:%s:%s" % (
            datetime.now(timezone.utc).strftime("%Y%m%d"),
            hashlib.sha256(_client_ip(request).encode()).hexdigest()[:16])
        n = await cache.incr_day(key, _day_end_epoch())
        return n <= _anon_quota_limit()
    except Exception:
        return True  # 额度层故障绝不拦截业务


# 自解释错误模型（十诫第6条：错误必须带可执行hint）


def _agent_error(request, exc, error, got, hint, **extra):
    import json
    from fastapi.responses import JSONResponse
    payload = dict(error=error, got=str(got)[:64], hint=hint)
    payload.update(extra)
    return JSONResponse(status_code=exc.status_code if hasattr(exc, "status_code") else 422,
                        content=payload)


from fastapi.exceptions import RequestValidationError


def _validation_to_agent(request, exc: RequestValidationError):
    """FastAPI默认422(工程师语言) -> agent可执行格式。"""
    for err in exc.errors():
        loc = err.get("loc", [])
        field = loc[-1] if loc else "?"
        got = err.get("input", "")
        if field == "chain":
            return _agent_error(
                request, exc, "invalid_chain", got,
                "use 'solana' (not 'sol') or 'eth'/'bsc'",
                valid=["eth", "bsc", "solana"])
        if field == "action":
            return _agent_error(
                request, exc, "invalid_action", got,
                "use 'swap' or 'approve'",
                valid=["swap", "approve"])
        if field == "target":
            return _agent_error(
                request, exc, "invalid_target", got,
                "contract/pool address, 8-64 chars (0x... or solana base58)")
    return _agent_error(
        request, exc, "invalid_request", exc.errors()[:1],
        "see /llms.txt for full API spec")


def create_app(runner=None) -> FastAPI:
    from contextlib import asynccontextmanager

    from atg.config import SETTINGS

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.repo = None
        app.state.cache = None
        if runner is None:
            from atg.cache.redis_client import VerdictCache
            try:
                c = VerdictCache()
                await c.get("__ping__", "__ping__", "__ping__")
                app.state.cache = c
            except Exception:
                app.state.cache = None  # Redis不可用=无缓存模式
            from atg.db.repo import make_repo
            app.state.repo = await make_repo(SETTINGS.database_url)  # PG不可达=NullRepo
            app.state.runner = None  # 懒初始化标志
        else:
            app.state.runner = runner
        yield
        if app.state.cache is not None:
            try:
                await app.state.cache.close()
            except Exception:
                pass
        if app.state.repo is not None:
            try:
                await app.state.repo.close()
            except Exception:
                pass

    app = FastAPI(title="AgentTradeGuard", version=__version__,
                  lifespan=lifespan,
                  exception_handlers={RequestValidationError:
                                      _validation_to_agent})
    app.state.runner = runner

    LLMS_TXT = Path(__file__).resolve().parents[2] / "docs" / "llms.txt"

    @app.get("/.well-known/llms.txt", response_class=None)
    @app.get("/llms.txt")
    def llms_txt():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(LLMS_TXT.read_text())

    AGENTS_MD = Path(__file__).resolve().parents[2] / "AGENTS.md"

    @app.get("/AGENTS.md")
    def agents_md():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(AGENTS_MD.read_text())

    @app.get("/v1/health")
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.get("/v1/check")
    async def check(
        request: Request,
        chain: str = Query(min_length=2, max_length=20),
        target: str = Query(min_length=8, max_length=64),
        action: str = Query("swap"),
        amount: Optional[str] = None,
    ) -> CheckResponse:
        chain = normalize_chain(chain)
        if chain not in ("eth", "bsc", "solana"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=422, content=dict(
                error="invalid_chain", got=chain,
                hint="use 'solana' (not 'sol') or 'eth'/'bsc'",
                valid=["eth", "bsc", "solana"]))
        action = action.strip().lower()
        if action not in ("swap", "approve"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=422, content=dict(
                error="invalid_action", got=action,
                hint="use 'swap' or 'approve'",
                valid=["swap", "approve"]))
        # ── 增长官M1：身份/归因/匿名额度（十诫4:先体验后注册）──
        token = (request.headers.get("x-atg-token")
                 or request.headers.get("x-guarddog-token") or "").strip()
        agent_id = _agent_id(request)
        source = _source_of(request)
        if not token and not await _anon_quota_ok(app, request):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=429, content=dict(
                error="quota_exceeded",
                hint="free tier is %d checks/day per IP; DM @OnchainGuardDog "
                     "for a beta token (unlimited during beta)"
                     % _anon_quota_limit(),
                reset_at=datetime.fromtimestamp(
                    _day_end_epoch(), tz=timezone.utc).isoformat()))
        if app.state.runner is None:
            if os.environ.get("ATG_MOCK") == "1":
                reasons = ["mock mode: ATG_MOCK=1"]
                payload = dict(chain=chain, target=target.lower(),
                               action=action, verdict="PASS",
                               risk_score=0, reasons=reasons)
                snap = hashlib.sha256(json.dumps(
                    payload, sort_keys=True).encode()).hexdigest()
                return CheckResponse(risk_score=0, verdict="PASS",
                                     reasons=reasons, covered=True,
                                     checked_at=datetime.now(timezone.utc),
                                     snapshot_hash=snap)
            from atg.engine.runner import CheckRunner
            app.state.runner = CheckRunner(cache=app.state.cache,
                                           repo=app.state.repo)
        out = await app.state.runner.check(chain, target, action, amount,
                                           agent_id=agent_id, source=source)
        return CheckResponse(
            risk_score=out["risk_score"], verdict=out["verdict"],
            reasons=out["reasons"], covered=out["covered"],
            checked_at=out["checked_at"], snapshot_hash=out["snapshot_hash"],
            data_limited=out.get("data_limited", False),
            unknown_token=out.get("unknown_token", False))

    @app.get("/v1/stats")
    async def stats(request: Request,
                    days: int = Query(7, ge=1, le=90)) -> dict:
        """增长漏斗统计（增长官M1）。ATG_STATS_TOKEN 设置后需
        X-ATG-Token 匹配；未设置=开放（nginx 侧不对外暴露即可）。"""
        want = os.environ.get("ATG_STATS_TOKEN", "")
        if want:
            got = (request.headers.get("x-atg-token") or "").strip()
            if got != want:
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=401, content=dict(
                    error="unauthorized", hint="X-ATG-Token required"))
        repo = getattr(app.state, "repo", None)
        if repo is None or hasattr(repo, "stats") is False:
            return dict(days=days, error="stats_unavailable",
                        hint="PG unreachable - analytics degraded")
        try:
            out = await repo.stats(days)
            out["days"] = days
            out["quota"] = dict(anon_daily_limit=_anon_quota_limit())
            return out
        except Exception as e:
            return dict(days=days, error="stats_failed",
                        hint=str(e)[:120])

    # 1x1 透明 GIF：X 帖 -> guarddog.top 引流埋点（增长官M1）
    _PIXEL = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff"
              b"\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00"
              b"\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")

    @app.get("/t.gif")
    async def pixel(request: Request,
                    utm_source: Optional[str] = Query(None, max_length=64),
                    utm_campaign: Optional[str] = Query(None, max_length=64),
                    utm_content: Optional[str] = Query(None, max_length=64)):
        if getattr(app.state, "repo", None) is not None:
            try:
                await app.state.repo.record_event(
                    utm_source=(utm_source or "")[:64] or None,
                    utm_campaign=(utm_campaign or "")[:64] or None,
                    utm_content=(utm_content or "")[:64] or None,
                    referer=(request.headers.get("referer") or "")[:200]
                    or None,
                    ua=(request.headers.get("user-agent") or "")[:200]
                    or None,
                    ip_hash=hashlib.sha256(
                        _client_ip(request).encode()).hexdigest()[:16])
            except Exception:
                pass  # 埋点失败静默
        return Response(content=_PIXEL, media_type="image/gif",
                        headers={"Cache-Control": "no-store"})

    return app


app = create_app()