# -*- coding: utf-8 -*-
"""验证推广尾巴清洗（PROMO_RE）是否「该删的删掉、不该删的别动」。

三组测试：
  A. 真实中招样本（today.json 里的 4 条爱范儿摘要）→ 必须清干净
  B. 误删回归（合法句子里的"关注""欢迎"）→ 必须原样保留
  C. 端到端：现场抓爱范儿 feed，走 clean_text + make_summary，对比清理前后

用法：用带 feedparser 的解释器跑
      .../python/envs/rss/Scripts/python.exe tools/diag_promo.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fetch_rss  # noqa: E402
from fetch_rss import clean_text, make_summary, ZW_RE, PROMO_RE  # noqa: E402

PRO = re.compile(r"微信号|欢迎关注|更多精彩内容|扫码关注|点击关注")

print("=" * 70)
print("A. 真实中招样本（today.json 里带推广尾巴的摘要）")
d = json.loads((ROOT / "data" / "today.json").read_text(encoding="utf-8"))
hits = []
for s in d["sections"]:
    for it in s["items"]:
        if PRO.search(it.get("summary", "")):
            hits.append(it)
print(f"  产物里带推广尾巴的条目: {len(hits)} 条（清洗前的存量数据）")
for it in hits:
    before = it["summary"]
    after = clean_text(before)
    short = " ← 剩不足20字，会触发抓正文补全" if len(after) < 20 else ""
    print(f"  · {it['title'][:34]}")
    print(f"      清理前({len(before)}字): {before[:76]}")
    print(f"      清理后({len(after)}字): {after[:76]}{short}")

print()
print("=" * 70)
print("B. 误删回归（这些**不该**被动）")
cases = [
    ("合法：关注度", "苹果发布会引发业界广泛关注，多家机构上调预期。"),
    ("合法：关注我们的隐私", "监管趋严，更多人开始关注我们的隐私如何被使用。"),
    ("合法：欢迎", "欢迎来到 AI 时代，算力成为新的生产资料。"),
    ("合法：扫码支付", "微信扫码支付日均笔数再创新高。"),
    ("中招：爱范儿尾巴", "最卷一夜！ #欢迎关注爱范儿官方微信公众号：爱范儿（微信号：ifanr），更多精彩内容第一时间为您奉上。"),
    ("中招：尾部广告", "模型能力大幅提升。扫码关注公众号获取更多资讯。"),
]
bad = 0
for label, s in cases:
    out = clean_text(s)
    should_change = label.startswith("中招")
    changed = out != s.strip()
    ok = changed == should_change
    if not ok:
        bad += 1
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}")
    if changed:
        print(f"          -> {out}")
print(f"  → 误删/漏删: {bad} 个")

print()
print("=" * 70)
print("C. 端到端：现场抓爱范儿 feed（清理前 vs 清理后）")
try:
    import urllib.request
    req = urllib.request.Request("https://www.ifanr.com/feed",
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; diag/1.0)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        xml = r.read(400_000).decode("utf-8", "replace")
except Exception as e:
    print(f"  抓取失败: {type(e).__name__}: {e}")
    xml = ""

if xml:
    print(f"  原始 feed 长度 {len(xml)} 字符")
    print(f"  ZW_RE 命中 {len(ZW_RE.findall(xml))} | PROMO_RE 命中 {len(PROMO_RE.findall(xml))}")
    descs = re.findall(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", xml, re.S)
    cleaned_n = 0
    wo = 0
    for raw in descs:
        before = raw
        after = clean_text(raw)
        if after != before.strip():
            cleaned_n += 1
        if PRO.search(after):
            wo += 1
    print(f"  description 共 {len(descs)} 条 | 被 clean_text 改动 {cleaned_n} 条")
    print(f"  清理后仍含推广文案: {wo} 条  {'✅' if wo == 0 else '❌'}")

    # 抽 3 条带推广的看前后
    shown = 0
    for raw in descs:
        b = clean_text(raw)
        if PRO.search(raw) or "ifanr" in raw:
            print(f"  --- 样本 {shown+1} ---")
            print(f"      前: {raw[:110]}")
            print(f"      后: {b[:110]}")
            shown += 1
            if shown >= 3:
                break

print()
print("=" * 70)
print("E. 产物体检（当前 data/today.json）")
items = [it for s in d["sections"] for it in s["items"]]
ZW = re.compile(r"[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\u206a-\u206f\ufeff]")
print(f"  条数 {len(items)}")
print(f"  摘要含推广文案 : {sum(1 for i in items if PRO.search(i.get('summary', '')))}")
print(f"  标题含零宽字符 : {sum(1 for i in items if ZW.search(i['title']))}")
print(f"  摘要含零宽字符 : {sum(1 for i in items if ZW.search(i.get('summary', '')))}")
print(f"  摘要 <20 字     : {sum(1 for i in items if len(i.get('summary', '')) < 20)}")
print(f"  摘要 <25 字     : {sum(1 for i in items if len(i.get('summary', '')) < 25)}")
print()
print("  爱范儿条目（改前 4/6 条摘要末尾挂广告）：")
for s in d["sections"]:
    for it in s["items"]:
        if it["source"] == "爱范儿":
            sm = it.get("summary", "")
            print(f"    [{len(sm):3d}字] {it['title'][:42]}")
            print(f"            {sm[:96]}")
            print(f"            推广残留: {'❌ 有' if PRO.search(sm) else '✅ 无'}")

