"""L2 address profile rules. Creator honeypot gradient (review 2026-10-16):
0=pass / 1=warn / 2=warn+strong text / >=3=block. No undefined band.
"""
from atg.engine.findings import Finding, SEV_WARN, SEV_BLOCK, tag


def assess_l2(gp):
    fs = []
    n = gp.get("honeypot_with_same_creator", 0)
    if n >= 3:
        fs.append(Finding("l2_creator_hp", SEV_BLOCK,
                          "创建者地址关联 %d 个蜜罐（>=3，连环骗局）" % n,
                          tag("l2")))
    elif n == 2:
        fs.append(Finding("l2_creator_hp", SEV_WARN,
                          "创建者地址关联 2 个蜜罐（高度疑似连环骗局）",
                          tag("l2")))
    elif n == 1:
        fs.append(Finding("l2_creator_hp", SEV_WARN,
                          "创建者地址关联 1 个蜜罐", tag("l2")))
    return fs