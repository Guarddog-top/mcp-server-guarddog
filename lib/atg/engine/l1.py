"""L1 static scan rules (GoPlus fields + Etherscan verification).
Tax thresholds per chain (approved 2026-10-14): eth 30%, bsc 45% initial;
values are fractions (0.35 = 35%) pending regression-set calibration.
"""
from atg.engine.findings import Finding, SEV_WARN, SEV_BLOCK, tag

SELL_TAX_BLOCK = dict(eth=0.30, bsc=0.45)
BUY_TAX_WARN = 0.10


def assess_l1(chain, gp, es):
    fs = []
    if gp["is_honeypot"]:
        fs.append(Finding("l1_honeypot", SEV_BLOCK,
                          "蜜罐特征：买入后无法卖出（GoPlus honeypot=1）", tag("l1")))
    st = gp.get("sell_tax")
    if st is not None and st >= SELL_TAX_BLOCK[chain]:
        fs.append(Finding("l1_sell_tax", SEV_BLOCK,
                          "卖出税 %.0f%%≥阈值 %.0f%%（%s链）"
                          % (st * 100, SELL_TAX_BLOCK[chain] * 100, chain), tag("l1")))
    bt = gp.get("buy_tax")
    if bt is not None and bt >= BUY_TAX_WARN:
        fs.append(Finding("l1_buy_tax", SEV_WARN,
                          "买入税 %.0f%%≥10%%" % (bt * 100), tag("l1")))
    if not es["verified"]:
        fs.append(Finding("l1_unverified", SEV_WARN,
                          "合约未开源验证（Etherscan无源码）", tag("l1")))
    if gp["is_mintable"]:
        if gp["hidden_owner"] or not es["verified"]:
            fs.append(Finding("l1_mintable", SEV_WARN,
                              "合约可增发且未开源/藏owner（is_mintable=1 复合）",
                              tag("l1")))
        else:
            # CAKE/USDT等中心化铸币=合法设计：开源+明owner的可铸币降为提示
            fs.append(Finding("l1_mintable", 10,
                              "合约可增发（开源+owner公开，正常设计）",
                              tag("l1")))
    if gp["hidden_owner"]:
        fs.append(Finding("l1_hidden_owner", SEV_WARN,
                          "隐藏owner权限（hidden_owner=1）", tag("l1")))
    if gp["selfdestruct"]:
        fs.append(Finding("l1_selfdestruct", SEV_WARN,
                          "合约含自毁路径（selfdestruct=1）", tag("l1")))
    if gp["cannot_buy"]:
        fs.append(Finding("l1_cannot_buy", SEV_WARN,
                          "当前状态限制买入（cannot_buy=1）", tag("l1")))
    return fs