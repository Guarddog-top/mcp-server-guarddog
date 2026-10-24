"""Response schemas (/v1/*)."""
from datetime import datetime
from typing import List
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str


class CheckResponse(BaseModel):
    risk_score: int
    verdict: str  # PASS | WARN | BLOCK
    reasons: List[str]
    covered: bool
    checked_at: datetime
    snapshot_hash: str
    data_limited: bool = False  # 数据源缺失标注（既不放行也不拦截）
    unknown_token: bool = False  # v0.4: 源健康但无记录（与data_limited严格分离）
