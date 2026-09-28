# -*- coding: utf-8 -*-
"""校验 latest.html 是否达标（卡片数/板块数/乱码/h1/英文标题）。"""
import re
import sys
import io

PATH = r"D:\WorkBuddyData\ai-daily-briefing\data\latest.html"

with io.open(PATH, "r", encoding="utf-8", errors="replace") as f:
    html = f.read()

# 前缀匹配：卡片 class 现为 "card reveal [wide]"，不能再用 class="card" 全等
cards = len(re.findall(r'<article class="card', html))
sections = len(re.findall(r'<section class="section"', html))
bad = html.count("\ufffd")

# 源站推广尾巴必须被清洗掉，不准出现在页面任何位置
# （爱范儿实测会给每条 description 挂 40 字"欢迎关注…微信号…"）
PROMO = re.compile(r"微信号|欢迎关注|更多精彩内容|扫码关注|点击关注")
promo = PROMO.findall(html)

m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
h1 = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else "(未找到)"

titles = re.findall(r'<h3 class="card-title"[^>]*>(.*?)</h3>', html, re.S)
titles = [re.sub(r"<[^>]+>", "", t).strip() for t in titles]

eng = []
for t in titles:
    cjk = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
    letters = sum(1 for ch in t if ch.isascii() and ch.isalpha())
    ratio = cjk / max(len(t), 1)
    if ratio < 0.15 and letters >= 8:
        eng.append(t)

ok = (cards >= 15 and sections >= 4 and bad == 0
      and h1 == "今日 AI 圈发生了什么" and len(eng) == 0 and not promo)

print("cards      =", cards, "(>=15)", "OK" if cards >= 15 else "FAIL")
print("sections   =", sections, "(>=4)", "OK" if sections >= 4 else "FAIL")
print("U+FFFD     =", bad, "(==0)", "OK" if bad == 0 else "FAIL")
print("推广残留   =", len(promo), "(==0)", "OK" if not promo else "FAIL")
for p in promo[:5]:
    print("   [PROMO]", p)
print("h1         =", h1, "OK" if h1 == "今日 AI 圈发生了什么" else "FAIL")
print("英文标题数 =", len(eng), "(==0)", "OK" if not eng else "FAIL")
for t in eng:
    print("   [EN]", t[:90])
print("titles_total =", len(titles))
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
