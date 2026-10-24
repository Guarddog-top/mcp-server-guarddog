"""ATG config: secrets via environment (.env file auto-loaded if present,
docker injects env directly). Bug lesson 2026-10-30: without .env loading,
fresh processes ran with EMPTY etherscan key -> whole blind exam ran with
Etherscan dead (disclosed in v0.4 report)."""
import os
from pathlib import Path


def _load_dotenv():
    p = Path(__file__).resolve().parents[1] / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Settings:
    """动态读env（访问时取值）：修复"import时快照导致后设env无效"的
    测试间污染/部署时序bug（2026-10-20全量套件实锤，.env同族教训）。"""

    @property
    def etherscan_api_key(self) -> str:
        return _env("ETHERSCAN_API_KEY")

    @property
    def goplus_key(self) -> str:
        return _env("GOPLUS_KEY")

    @property
    def goplus_secret(self) -> str:
        return _env("GOPLUS_SECRET")

    @property
    def redis_url(self) -> str:
        return _env("REDIS_URL", "redis://localhost:6379/0")

    @property
    def database_url(self) -> str:
        return _env("DATABASE_URL", "postgresql://atg:atg@localhost:5432/atg")

    @property
    def cache_ttl_sec(self) -> int:
        return int(_env("CACHE_TTL_SEC", "600"))

    @property
    def block_ttl_sec(self) -> int:
        return int(_env("BLOCK_TTL_SEC", "3600"))

    @property
    def warn_ttl_sec(self) -> int:
        return int(_env("WARN_TTL_SEC", "300"))


SETTINGS = Settings()
