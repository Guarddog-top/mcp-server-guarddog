"""GuardDog X bot 骨架（P0）：@提及查询 -> /v1/check -> 双格式回复。
凭据全走环境变量（X-ATG-*）; DRY_RUN=1 只打印不发送（无凭据可开发自测）。
部署: 守门人德国机; 运行: python -m atg.xbot.bot
"""
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from atg.xbot.format import format_reply

ATG_BASE = os.environ.get("ATG_BASE", "https://atg.aiargus.world:2053")
ATG_TOKEN = os.environ.get("ATG_TOKEN", "")
X_BEARER = os.environ.get("X_BEARER_TOKEN", "")
DRY_RUN = os.environ.get("XBOT_DRY_RUN", "1") == "1"

ADDR = re.compile(r"(0x[0-9a-fA-F]{8,64}|[1-9A-HJ-NP-Za-km-z]{32,44})")
CHAIN_OF = dict(eth="eth", bsc="bsc", solana="solana", sol="solana")


def check(chain, target):
    q = urllib.parse.urlencode(dict(chain=chain, target=target))
    req = urllib.request.Request(ATG_BASE + "/v1/check?" + q)
    if ATG_TOKEN:
        req.add_header("X-ATG-Token", ATG_TOKEN)
    req.add_header("X-ATG-Source", "xbot")  # 增长官M1归因：xbot流量可分离
    with urllib.request.urlopen(req, timeout=15) as r:
        import json
        return json.loads(r.read())


def parse_mention(text):
    """'check 0xabc on bsc' / 'sol So111...' -> (chain, addr)"""
    m = ADDR.search(text)
    if not m:
        return None
    addr = m.group(0)
    low = text.lower()
    chain = next((v for k, v in CHAIN_OF.items() if k in low), "eth")
    return chain, addr


def process_text(text):
    parsed = parse_mention(text)
    if not parsed:
        return None
    chain, addr = parsed
    payload = check(chain, addr)
    return format_reply(payload, chain=chain)


def main():
    if not X_BEARER and not DRY_RUN:
        print({"error": "missing_creds",
               "hint": "set X_BEARER_TOKEN or XBOT_DRY_RUN=1"})
        sys.exit(1)
    if DRY_RUN:
        demo = "hey check 0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82 on bsc"
        print("[dry-run] in:", demo)
        print("[dry-run] out:\n" + str(process_text(demo)))
        return
    # 真实模式: 轮询mentions(凭据到位后启用过滤端点)
    while True:
        time.sleep(30)  # TODO: GET /2/tweets/search/recent 问答轮询


if __name__ == "__main__":
    main()
