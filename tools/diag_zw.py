# -*- coding: utf-8 -*-
"""诊断 fetch_rss.py 里 ZW_RE（零宽/不可见字符剔除）是否真有必要、是否会误伤。

做三件事：
  A. 拿现有产物 today.json 统计（清理后应为 0）
  B. 现场抓几个源，统计**清理前**的原始 XML 里有哪些不可见字符 —— 这才是判断
     "这个正则有没有用" 的唯一依据
  C. 用真实 emoji 组合序列测 ZW_RE 会不会把 emoji 切坏

用法：python tools/diag_zw.py
"""
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ZW_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\u206a-\u206f\ufeff]")

# 与 ZW_RE 同类、但正则**没**覆盖的不可见/格式字符
NOT_COVERED = [
    (0x00AD, "SOFT HYPHEN 软连字符（也常被拿来做水印）"),
    (0x061C, "ARABIC LETTER MARK"),
    (0x180E, "MONGOLIAN VOWEL SEPARATOR"),
    (0x2000, "EN QUAD 半角空格"),
    (0x2028, "LINE SEPARATOR"),
    (0x2065, "未分配码位"),
    (0xFE00, "VARIATION SELECTOR-1"),
    (0xFE0F, "VARIATION SELECTOR-16（emoji 变体选择符）"),
    (0xE0001, "LANGUAGE TAG"),
]

# 真实 emoji 组合序列（用 chr() 拼，避免转义串被二次解码搞坏）
EMOJI_CASES = [
    ("一家四口 👨\u200d👩\u200d👧\u200d👦", [0x1F468, 0x200D, 0x1F469, 0x200D, 0x1F467, 0x200D, 0x1F466]),
    ("女程序员 👩\u200d💻", [0x1F469, 0x200D, 0x1F4BB]),
    ("彩虹旗 🏳\ufe0f\u200d🌈", [0x1F3F3, 0xFE0F, 0x200D, 0x1F308]),
    ("键帽 1\ufe0f\u20e3", [0x31, 0xFE0F, 0x20E3]),
    ("波斯语 ZWNJ 连写", [0x645, 0x6CC, 0x200C, 0x631, 0x648, 0x645]),
]


def name_of(ch):
    try:
        return unicodedata.name(ch)
    except ValueError:
        return "<无名称>"


def scan(text, label):
    hits = {}
    for ch in text:
        cp = ord(ch)
        if cp in (0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0xFEFF) or \
           0x202A <= cp <= 0x202E or 0x2060 <= cp <= 0x206F:
            hits[cp] = hits.get(cp, 0) + 1
    zw_hits = len(ZW_RE.findall(text))
    print(f"  [{label}] 长度 {len(text)} 字符 | ZW_RE 命中 {zw_hits}")
    for cp, n in sorted(hits.items()):
        covered = bool(ZW_RE.search(chr(cp)))
        print(f"      U+{cp:04X} {name_of(chr(cp))} x{n} "
              f"{'[已覆盖]' if covered else '[未覆盖]'}")
    if not hits:
        print("      （未发现零宽/格式字符）")
    return zw_hits


def fetch(url, limit=400_000):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ai-briefing-diagnostic/1.0)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read(limit)
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:4000], re.I)
    cs = m.group(1).decode() if m else "utf-8"
    return raw.decode(cs, errors="replace")


def main():
    print("=" * 68)
    print("A. 现有产物（已清理过，预期 0）")
    for f in ["data/today.json", "data/latest.html"]:
        p = ROOT / f
        if p.exists():
            scan(p.read_text(encoding="utf-8"), f)

    print()
    print("=" * 68)
    print("B. 现场抓取原始 feed —— 看「清理前」到底有没有脏字符")
    targets = [
        ("爱范儿", "https://www.ifanr.com/feed"),
        ("IT之家", "https://www.ithome.com/rss/"),
        ("少数派", "https://sspai.com/feed"),
        ("量子位", "https://www.qbitai.com/feed"),
        ("199IT", "https://www.199it.com/feed"),
    ]
    for name, url in targets:
        try:
            xml = fetch(url)
        except Exception as e:
            print(f"  [{name:6s}] 抓取失败: {type(e).__name__}: {e}")
            continue
        scan(xml, name)

    print()
    print("=" * 68)
    print("C. ZW_RE 对真实 emoji 组合序列的影响")
    broken = 0
    for label, cps in EMOJI_CASES:
        raw = "".join(chr(c) for c in cps)
        out = ZW_RE.sub("", raw)
        same = (out == raw)
        if not same:
            broken += 1
        print(f"  {label:22s} {len(raw)} 字符 -> {len(out)} 字符  "
              f"{'✓ 不受影响（该序列不含被剔除的字符）' if same else '⚠️ 被切坏'}")
    print(f"  → {broken}/{len(EMOJI_CASES)} 组被切坏")

    print()
    print("=" * 68)
    print("D. ZW_RE 未覆盖的同类字符（是否值得补）")
    for cp, desc in NOT_COVERED:
        covered = bool(ZW_RE.search(chr(cp)))
        ws = bool(re.match(r"\s", chr(cp)))
        print(f"  U+{cp:05X}  {desc:42s} ZW_RE={covered}  \\s匹配={ws}")

    print()
    print("=" * 68)
    print("E. 【关键】爱范儿里 U+200D / U+200C / U+200B 的真实上下文")
    print("   判断依据：夹在两个 emoji 之间 = 真组合序列（剔了会切坏）；")
    print("   夹在普通汉字/字母之间 = 散装水印（剔了才对）。")
    try:
        xml = fetch("https://www.ifanr.com/feed")
    except Exception as e:
        print(f"  抓取失败: {e}")
        xml = ""

    def desc(ch):
        if not ch:
            return "(边界)"
        cp = ord(ch)
        if 0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF:
            return f"EMOJI U+{cp:04X}"
        if cp < 0x80:
            return repr(ch)
        return f"U+{cp:04X} {name_of(ch)[:22]}"

    for cp in (0x200D, 0x200C, 0x200B):
        total = xml.count(chr(cp))
        print(f"  --- U+{cp:04X} {name_of(chr(cp))}  共 {total} 次 ---")
        shown = 0
        for m in re.finditer(re.escape(chr(cp)), xml):
            i = m.start()
            if shown >= 6:
                break
            print(f"      前: {desc(xml[i-1:i]):34s} 后: {desc(xml[i+1:i+2])}")
            shown += 1

    print()
    print("=" * 68)
    print("F. 端到端影响：爱范儿标题过一遍 clean_text，看有几个标题被改动")
    from fetch_rss import clean_text
    titles = re.findall(r"<title>(.*?)</title>", xml, re.S)
    titles = [t for t in titles if t.strip()]
    changed = 0
    emoji_broken = 0
    for t in titles:
        c = clean_text(t)
        if c != re.sub(r"\s+", " ", t).strip():
            changed += 1
        # 原始标题含 emoji，清理后 emoji 变少 = 被切坏
        e0 = len([x for x in t if 0x1F000 <= ord(x) <= 0x1FAFF])
        e1 = len([x for x in c if 0x1F000 <= ord(x) <= 0x1FAFF])
        if e0 and e1 < e0:
            emoji_broken += 1
    print(f"  标题总数 {len(titles)} | clean_text 后有改动 {changed} 个")
    print(f"  其中 emoji 数量变少的（被切坏）: {emoji_broken} 个")
    print(f"  → 若 emoji_broken == 0，说明当前源里 ZWJ 都是散装水印，剔除无副作用")


if __name__ == "__main__":
    main()
