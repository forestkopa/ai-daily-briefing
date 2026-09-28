#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS 抓取器 —— 零 token 生成 AI 日报数据

流程：拉取多个 RSS 源 -> 关键词过滤出 AI 相关 -> 按板块归类 -> 去重排序 -> 输出 data/<日期>.json

依赖：feedparser（隔离 venv: binaries/python/envs/rss）
用法：
    python fetch_rss.py                      # 抓最近 48 小时，输出到 data/<今天>.json
    python fetch_rss.py --hours 72           # 放宽到 72 小时
    python fetch_rss.py -o data/test.json    # 指定输出
    python fetch_rss.py --limit 8            # 每个板块最多 8 条
"""

import argparse
import hashlib
import html as htmllib
import json
import re
import socket
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    import feedparser
except ImportError:
    print("[x] 缺少 feedparser。请用隔离 venv 运行：", file=sys.stderr)
    print('    C:/Users/Administrator/.workbuddy/binaries/python/envs/rss/Scripts/python.exe '
          'fetch_rss.py', file=sys.stderr)
    sys.exit(2)

socket.setdefaulttimeout(25)
BASE = Path(__file__).resolve().parent

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")

CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------- 信息源配置
# section: 归属板块；kw: 该源是否需要关键词过滤（全站源必须开）
# skip: 标题命中即丢弃（广告、促销、活动报名等）
# 全中文信源。已剔除所有英文源（OpenAI / DeepMind / Together / Ollama / Qwen /
# TechCrunch / The Verge / Wired / arXiv / MIT TR / HN / Lobsters / GitHub Trending），
# 并靠 is_zh() 做兜底，保证页面上不出现英文内容。
SOURCES = [
    # ============ 模型发布 / 更新 ============
    # 模型发布本身低频，且国内厂商多在自家公众号/官网发文，无稳定中文 RSS。
    # 这里改用「AI 垂直媒体 + 厂商动态」的中文内容填充该板块。
    {"name": "量子位",           "url": "https://www.qbitai.com/feed",
     "section": "sec-model", "kw": True,
     "skip": r"(?i)招聘|报名|直播预告|抽奖|融资|榜单"},
    {"name": "钛媒体",           "url": "https://www.tmtpost.com/rss.xml",
     "section": "sec-model", "kw": True,
     "skip": r"(?i)招聘|报名|直播"},

    # ============ 产品发布 / 更新 ============
    {"name": "开源中国",         "url": "https://www.oschina.net/news/rss",
     "section": "sec-product", "kw": True,
     "skip": r"(?i)版本发布：?$|更新日志"},
    {"name": "InfoQ 中文",       "url": "https://www.infoq.cn/feed",
     "section": "sec-product", "kw": True},
    {"name": "IT之家",           "url": "https://www.ithome.com/rss/",
     "section": "sec-product", "kw": True,
     "skip": r"(?i)促销|开售|上市：|发布：.*元|图赏|上手"},

    # ============ 行业动态 ============
    {"name": "雷峰网",           "url": "https://www.leiphone.com/feed",
     "section": "sec-industry", "kw": True, "max_per_source": 8,
     "skip": r"(?i)招聘|报名|活动|峰会预告"},
    {"name": "Solidot",         "url": "https://www.solidot.org/index.rss",
     "section": "sec-industry", "kw": True, "max_per_source": 5},
    {"name": "量子位 行业",       "url": "https://www.qbitai.com/feed",
     "section": "sec-industry", "kw": True, "max_per_source": 6,
     "skip": r"(?i)招聘|报名|直播预告|抽奖"},

    # ============ 研报与数据 ============
    # arXiv 纯英文已移除。改用中文机构/媒体发布的 AI 市场与数据洞察。
    # 199IT 的 feed 不带日期，标 no_date 走当前时间兜底。
    {"name": "199IT",           "url": "https://www.199it.com/feed",
     "section": "sec-paper", "kw": True, "no_date": True, "max_per_source": 10,
     "skip": r"(?i)撒哈拉|非洲|粮食|营养|车企|面板|显示器|手环|光缆|酒店|旅游|营销|品牌|主机游戏|智能手机出货"},

    # ============ 技巧与观点 ============
    # 注意：同一 feed 不要在两个板块重复引用——dedup 按标题去重会把后引用
    # 的那份吃掉，导致某个板块莫名变空。故量子位/钛媒体各自只在一个板块。
    {"name": "少数派",           "url": "https://sspai.com/feed",
     "section": "sec-tips", "kw": True},
    {"name": "爱范儿",           "url": "https://www.ifanr.com/feed",
     "section": "sec-tips", "kw": True, "max_per_source": 6,
     "skip": r"(?i)体验：|评测|开箱|耳机|音箱|手表|手环|相机|镜头"},
    {"name": "快科技",           "url": "https://rss.mydrivers.com/rss.aspx?Tid=1",
     "section": "sec-tips", "kw": True, "max_per_source": 4,
     "skip": r"(?i)促销|开售|降价|到手价|图赏|无人机|游戏主机|PS\d|显示器|硬盘|内存条|智界|余承东|定档|上市|EAI机器人|长鑫|LPDDR"},
]

# ---------------------------------------------------------------- AI 关键词

# 强信号词：命中即可判定为 AI 相关（用于全站源的标题主判据）
AI_STRONG = re.compile(
    r"(?i)"
    r"人工智能|大模型|大语言模型|生成式|智能体|具身智能|机器学习|深度学习|神经网络|"
    r"算力|智算|推理芯片|训练芯片|英伟达|NVIDIA|"
    r"OpenAI|Anthropic|Claude|Gemini|DeepMind|DeepSeek|Qwen|通义|千问|豆包|Kimi|"
    r"智谱|GLM|阶跃|MiniMax|月之暗面|百川|零一万物|宇树|商汤|科大讯飞|文心|"
    r"Llama|Mistral|Grok|xAI|Hugging ?Face|Stable Diffusion|Midjourney|Sora|"
    r"Copilot|Cursor|Codex|RAG|Transformer|扩散模型|多模态|"
    r"词元|提示词|微调|蒸馏|模型对齐|幻觉|"
    r"人形机器人|自动驾驶|智能驾驶|语音模型|文生图|文生视频|AIGC|AGI|LLM|"
    r"GPT-?\d|Opus \d|Sonnet \d|Fable \d|Muse \d|Astra|DeepSeek|UnifoLM"
)

# 弱信号词：仅缩写，必须独立成词才算数（避免 "AI" 命中 "AIOps" 无关语境等误伤）
AI_WEAK = re.compile(r"(?i)(?:^|[^A-Za-z])(AI|A\.I\.)(?:$|[^A-Za-z])")

# 命中即丢弃的产物类型（全站源的标题噪音）
NOISE = re.compile(
    r"(?i)"
    r"^(派早报|早报|晚报|晨报|日报)\b|"
    r"^要闻|要闻提示|一周要闻|今日要闻|"
    r"^\[?广告\]?|赞助内容|"
    r"首发价|直降|到手价|优惠券|限时秒杀|预约量破|"
    r"正式开售|开启预售|官网降价|"
    r"涨价|售价|均价|跌至|创新低|"
    r"装机党|哭晕|亮了|真香"
)

# 即使命中 AI 关键词也应排除的伪相关（消费电子/游戏/无关行业）
FALSE_POSITIVE = re.compile(
    r"(?i)"
    r"耳机|耳夹|耳挂|音箱|手机壳|充电宝|电动单车|电摩|"
    r"游戏移植|主机游戏|手机游戏|手游|"
    r"新机|镜头|屏幕刷新率|快充|电池容量|"
    r"汽车|车型|续航里程|上市发布会|"
    r"天气|台风|地震|洪灾|粮仓"
)

# GitHub Trending 专用排除：科技周刊、招聘、股票、无关工具
GitHub_NOISE = re.compile(
    r"(?i)"
    r"weekly|awesome-list|interview|招聘|周刊|"
    r"stock|trading|trading platform|market platform|"
    r"boilerplate|template collection|roadmap|"
    r"english|学英语|cookbook|cheat sheet"
)

def is_ai_related(title: str, body: str) -> bool:
    """判断条目是否真的与 AI 相关。

    分三级，从严到宽：
      1. 标题命中强信号词  -> 判定相关
      2. 正文命中强信号词，且标题不含伪相关品类 -> 判定相关
      3. 标题命中弱信号词（独立成词的 AI/A.I.），且标题不含伪相关品类 -> 判定相关
    缩写只在标题里认，避免正文随口一提就被误判。
    """
    if AI_STRONG.search(title):
        return not FALSE_POSITIVE.search(title)
    if AI_WEAK.search(title):
        return not FALSE_POSITIVE.search(title)
    if AI_STRONG.search(body):
        return not FALSE_POSITIVE.search(title)
    return False

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
# 零宽 / 双向控制 / 不可见格式字符（如爱范儿在标题里塞的反抓取水印）。
# 注意：这些字符属 Unicode Cf 类，\s 不匹配，必须在 WS_RE 之前单独剔除，
# 否则会留在标题里导致复制/搜索/查重出现"看不见的乱码"。
ZW_RE = re.compile(r"[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\u206a-\u206f\ufeff]")
# ⚠️ 上表里的 200C/200D（ZWNJ/ZWJ）在"散装水印"之外的场景**不该剔**：
#    它们是 emoji 组合符，👨‍👩‍👧‍👦（1F468+200D+1F469+200D+1F467+200D+1F466）
#    剔完会被切成 4 个独立 emoji。
#    2026-09-24 实测：11 个源里这些字符的左右邻居全是 202C/200B/2061-2064，
#    属于散装水印排版，**没有一处夹在两个 emoji 之间**，故当前零误伤。
#    若将来接入带 emoji 的源，需重新评估是否把 200C/200D 摘出去。
#    U+00AD（软连字符）一并纳入：它同样是隐形水印常用字符，且 \s 不匹配。

# 源站推广尾巴。爱范儿的 description 实测形如：
#   "最卷一夜！ #欢迎关注爱范儿官方微信公众号：爱范儿（微信号：ifanr），更多精彩内容第一时间为您奉上。"
# 这 40 来字会吃掉 180 字摘要配额的两成，读者读完正文正好撞上广告；
# 而且它排在末尾，不加处理时**被 truncate 截掉的反而是正文**。
# 注意：剔除后若正文不足 20 字，make_summary 会自动去抓文章首段补内容，不会出现空卡。
PROMO_RE = re.compile(
    r"(?:[#＃]?\s*欢迎关注|更多精彩内容|扫码关注|长按识别|点击关注)"
    r"[^。！？]*(?:[。！？]|$)"
    r"|（?微信号[:：]\s*[\w.\-]+）?"
)

CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def cjk_ratio(s: str) -> float:
    """中文字符占比。用于判定条目是否为中文内容。"""
    if not s:
        return 0.0
    return len(CJK_RE.findall(s)) / len(s)


def is_zh(title: str, body: str = "") -> bool:
    """条目是否为中文内容。

    信源已全部换成中文站，但少量源（IT之家、抖音快讯类）会夹杂纯英文标题，
    或个别条目的标题只有数字/英文型号。这里以标题的中文字符占比兜底：
      标题 >= 12 字：中文占比 >= 0.20 即判定中文
      标题 <  12 字：要求更严（0.40），避免 "GPT-5" 这种短英文标题漏进来
    标题判定不足时，再看摘要前 200 字是否有成句中文。
    """
    t = title.strip()
    if t:
        need = 0.20 if len(t) >= 12 else 0.40
        if cjk_ratio(t) >= need:
            return True
    if body:
        head = body.strip()[:200]
        if len(CJK_RE.findall(head)) >= 15 and cjk_ratio(head) >= 0.25:
            return True
    return False


def clean_text(s: str) -> str:
    if not s:
        return ""
    s = htmllib.unescape(s)          # &#8217; -> ’ 之类
    s = TAG_RE.sub(" ", s)
    s = re.sub(r"^(arXiv:[\d.]+v\d+\s*)?Announce Type:\s*\w+\s*", "", s)
    s = re.sub(r"^Abstract:\s*", "", s)
    s = re.sub(r"(点击查看原文>|查看全文|阅读全文\s*$)", "", s)
    s = PROMO_RE.sub(" ", s)         # 源站推广尾巴（爱范儿"欢迎关注…微信号…"）
    s = ZW_RE.sub("", s)             # 先剔零宽/不可见字符，再规整空白
    s = WS_RE.sub(" ", s).strip()
    return s


def truncate(s: str, n: int = 180) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    for sep in ("。", "；", ". ", "！", "？"):
        p = cut.rfind(sep)
        if p > n * 0.55:
            return cut[: p + 1] if sep in "。；！？" else cut[: p + 1]
    return cut.rstrip("，,、 ") + "…"


def parse_date(entry):
    """返回带时区的 datetime，失败返回 None。"""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).astimezone(CST)
            except (ValueError, TypeError):
                pass
    return None


def entry_link(entry):
    link = entry.get("link") or ""
    if not link:
        for ln in entry.get("links", []):
            if ln.get("href"):
                link = ln["href"]
                break
    # 去掉 utm 跟踪参数
    link = re.sub(r"[?&](utm_[^=&]+|ref|source)=[^&]*", "", link)
    return link.rstrip("?&")


def fetch_source(src, cutoff):
    """抓取单个源，返回 (条目列表, 状态信息)。

    部分源（DeepMind、Hacker News）会间歇性超时或返回空，固加重试。
    """
    # 低频板块（模型发布 / 研报）单独放宽时间窗至 14 天
    if src.get("section") in ("sec-model", "sec-paper"):
        cutoff = min(cutoff, datetime.now(CST) - timedelta(hours=src.get("hours", 336)))

    entries, err = [], None
    for attempt in range(3):
        try:
            d = feedparser.parse(src["url"], agent=UA)
            entries = d.get("entries") or []
            if entries:
                break
            err = f"0 条 (status={d.get('status')})"
        except Exception as e:
            err = f"异常 {type(e).__name__}"
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))

    if not entries:
        return [], err or "0 条"

    max_ps = src.get("max_per_source", 30)
    skip_re = re.compile(src["skip"]) if src.get("skip") else None
    need_kw = src.get("kw", True)

    out = []
    for e in entries[: max(max_ps * 3, 40)]:
        title = clean_text(e.get("title", ""))
        if not title or len(title) < 6:
            continue
        if skip_re and skip_re.search(title):
            continue
        if NOISE.search(title):
            continue

        link = entry_link(e)
        if not link:
            continue

        dt = parse_date(e)
        if dt is None:
            if src.get("no_date"):        # 无日期源（199IT）：用当前时间兜底
                dt = datetime.now(CST)
            else:
                continue
        if dt < cutoff:
            continue

        body = clean_text(e.get("summary") or e.get("description") or "")

        if not is_zh(title, body):        # 中文兜底：英文条目直接丢弃
            continue

        if need_kw and not is_ai_related(title, body):
            continue

        out.append({
            "title": title,
            "source": src["name"],
            "summary_raw": body,
            "url": link,
            "dt": dt,
            "section": src["section"],
        })
        if len(out) >= max_ps:
            break

    # 无日期源（GitHub Trending）：仓库名本身无语义，只看描述判定
    # 注：GitHub Trending 属英文源，已从 SOURCES 移除。此分支保留，
    # 以便将来接入「中文项目描述」类的无日期源时复用同一套过滤。
    if not out and src.get("no_date"):
        for e in entries[:40]:
            title = clean_text(e.get("title", ""))
            body = clean_text(e.get("summary") or "")
            if not title or not body:
                continue
            # 只见描述里的强信号词，避免"周刊/招聘/股票"这类靠 AI_WEAK 混入
            if not AI_STRONG.search(body):
                continue
            if GitHub_NOISE.search(f"{title} {body}"):
                continue
            if not is_zh(title, body):    # 中文兜底：英文项目描述直接丢弃
                continue
            link = entry_link(e)
            if not link:
                continue
            out.append({
                "title": title,
                "source": src["name"],
                "summary_raw": body,
                "url": link,
                "dt": datetime.now(CST),
                "section": src["section"],
            })
            if len(out) >= 6:
                break

    return out, f"{len(out)} 条"


def dedup(items):
    """按标题归一化指纹去重，保留先出现的。"""
    seen, out = set(), []
    for it in items:
        norm = re.sub(r"[\s\W_]+", "", it["title"]).lower()[:60]
        fp = hashlib.md5(norm.encode("utf-8")).hexdigest()
        if fp in seen:
            continue
        seen.add(fp)
        out.append(it)
    return out


def make_summary(it):
    """生成卡片摘要正文。

    卡片本身已有大标题，摘要里不该再重复标题。所以这里只产出"正文"，
    标题由模板渲染。RSS 摘要质量参差：
      - 有些源（InfoQ、量子位）的 description 只是"点击查看原文"之类的占位符
      - 有些源（arXiv、IT之家）的 description 以标题开头，需裁掉重复前缀
      - 有些源（GitHub Trending）的 description 是英文项目描述
    正文不足时，回落到一句基于来源与板块的说明，避免空白。
    """
    title = it["title"].rstrip("。.…")
    s = truncate(it["summary_raw"], 180)

    # 占位符/无信息摘要黑名单
    if s:
        stripped = re.sub(r"[\s，,。.、；;：:！!？?…\-—>]+", "", s)
        if len(stripped) < 20 or stripped in ("点击查看原文", "查看全文", "阅读全文"):
            s = ""

    if s:
        s = strip_title_prefix(title, s)

    # HN 的 description 是 "Article URL: ... Comments URL: ..." 机器格式，压成一句
    if s:
        m = re.search(r"Article URL:\s*(\S+)", s)
        pts = re.search(r"Points:\s*(\d+)", s)
        if m:
            s = ""
            if pts:
                s = f"Hacker News 热议 {pts.group(1)} 分。"
            else:
                s = ""

    if not s or len(s) < 20:
        # 源摘要残缺（InfoQ/量子位 只给"点击查看原文"）时，尝试抓正文补一段
        fetched = fetch_article_lead(it["url"])
        if fetched:
            s = truncate(strip_title_prefix(title, fetched), 180)

    if not s or len(s) < 20:
        hint = {
            "sec-model": "模型或厂商层面的动态",
            "sec-product": "产品与工程实践",
            "sec-industry": "行业与产业层面的动向",
            "sec-paper": "市场与数据洞察",
            "sec-tips": "技巧、观点或开源项目",
        }.get(it.get("section", ""), "AI 领域动态")
        return f"来自 {it['source']} 的{hint}，详情请见原文。"

    return s


# 正文抓取缓存，避免重复请求
_LEAD_CACHE = {}


def fetch_article_lead(url: str, limit: int = 400) -> str:
    """抓取文章页面的首段正文，作为 RSS 摘要的兜底。

    只对摘要残缺的条目调用，失败静默返回空串（不阻断整体生成）。
    """
    if url in _LEAD_CACHE:
        return _LEAD_CACHE[url]

    lead = ""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=12, context=CTX) as r:
            raw = r.read(300_000)
        # 编码嗅探
        charset = "utf-8"
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:4000], re.I)
        if m:
            charset = m.group(1).decode("ascii", "ignore")
        page = raw.decode(charset, errors="replace")

        # 优先取 og:description / meta description
        for pat in (
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:description["\']',
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
        ):
            mm = re.search(pat, page, re.I | re.S)
            if mm:
                lead = clean_text(mm.group(1))
                if len(lead) >= 40:
                    break

        # 退而求其次：正文首段
        if len(lead) < 40:
            body = re.sub(r"(?is)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", page)
            for pm in re.finditer(r"<p[^>]*>(.*?)</p>", body, re.S):
                t = clean_text(pm.group(1))
                if len(t) >= 50:
                    lead = t
                    break
    except Exception:
        lead = ""

    _LEAD_CACHE[url] = lead
    return lead


def _norm_cmp(x: str) -> str:
    """归一化用于比较：去空白、标点、大小写。"""
    return re.sub(r"[\s\W_]+", "", x).lower()


def strip_title_prefix(title: str, body: str) -> str:
    """把 body 开头与 title 重复的片段去掉。

    摘要常以标题开头（如「RBS-Attention: Bounded ...。Long-context ...」），
    直接展示会出现「标题。标题。正文」的冗余。

    做法：在原文上做字符级扫描，跳过所有非字母数字字符后逐个比对标题字符；
    全部匹配成功即认为该前缀是标题的重复，在原文对应位置裁掉。
    """
    body = body.strip()
    if not body:
        return body

    # 依次用逐渐变短的标题前缀尝试；命中即裁
    for cut in (len(title), 28, 22, 16, 12, 8):
        prefix = title[:cut].strip()
        if len(prefix) < 6:
            continue
        # 归一化后的标题前缀
        npfx = _norm_cmp(prefix)
        if not npfx:
            continue

        i, k = 0, 0
        while i < len(body) and k < len(npfx):
            ch = body[i]
            if _norm_cmp(ch) or ch.isalnum():
                # 该位置是一个"有效字符"，与标题前缀比对
                if ch.lower() == npfx[k]:
                    k += 1
                else:
                    break
            i += 1

        if k >= len(npfx) and i > 0:
            body = body[i:].lstrip("：: ，,。.、；;·—-—>）)]】\"' ")
            return body.strip()

    return body.strip()


def build(data_out: Path, hours: int, per_section: Optional[int]):
    now = datetime.now(CST)
    cutoff = now - timedelta(hours=hours)

    all_items, report = [], []
    for src in SOURCES:
        items, status = fetch_source(src, cutoff)
        all_items.extend(items)
        report.append((src["name"], src["section"], status))
        print(f"  {status:<22} {src['name']}")

    all_items = dedup(all_items)

    # 板块配额：避免全站源（IT之家/快科技）把某一板块撑爆
    SECTION_CAP = {
        "sec-model": 6,
        "sec-product": 8,
        "sec-industry": 8,
        "sec-paper": 6,
        "sec-tips": 8,
    }

    by_sec = {}
    for it in all_items:
        by_sec.setdefault(it["section"], []).append(it)
    for sec in by_sec:
        by_sec[sec].sort(key=lambda x: x["dt"], reverse=True)
        cap = per_section or SECTION_CAP.get(sec)
        if cap:
            by_sec[sec] = by_sec[sec][:cap]

    SECTION_META = [
        ("sec-model",    "模型与厂商",     "layers"),
        ("sec-product",  "产品与工程",     "box"),
        ("sec-industry", "行业动态",       "trend"),
        ("sec-paper",    "研报与数据",     "book"),
        ("sec-tips",     "技巧与观点",     "bulb"),
    ]
    WEEKDAY = "周一周二周三周四周五周六周日"

    sections = []
    idx_title_map = {}
    for sid, name, icon in SECTION_META:
        items = by_sec.get(sid, [])
        if not items:
            continue
        entries = []
        for it in items:
            entries.append({
                "title": it["title"],
                "source": it["source"],
                "summary": make_summary(it),
                "url": it["url"],
                "date": it["dt"].strftime("%Y-%m-%d %H:%M"),
            })
        sections.append({"id": sid, "name": name, "icon": icon, "items": entries})
        idx_title_map[sid] = len(entries)

    total = sum(len(s["items"]) for s in sections)
    if total == 0:
        print("\n[x] 未抓到任何条目（可能时间窗太窄或网络异常）。", file=sys.stderr)
        return 1

    srcs_used = sorted({it["source"] for it in all_items})

    data = {
        "date": now.strftime("%Y-%m-%d"),
        "weekday": WEEKDAY[(now.weekday() * 2):(now.weekday() * 2) + 2],
        "title": "今日",
        "subtitle": "圈发生了什么",
        "tagline": f"由 RSS 自动聚合，来自 {len(srcs_used)} 个中文信息源的精选合辑（零 AI 调用）",
        "stats": [
            {"num": total, "label": "今日条数"},
            {"num": len(sections), "label": "分类板块"},
            {"num": len(srcs_used), "label": "收录信源"},
            {"num": "自动", "label": "每日更新"},
        ],
        "footerSource": {
            "name": " / ".join(srcs_used[:6]) + (" 等" if len(srcs_used) > 6 else ""),
            "url": "https://www.qbitai.com/",
        },
        "generatedBy": "fetch_rss.py",
        "sections": sections,
    }

    data_out.parent.mkdir(parents=True, exist_ok=True)
    data_out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[v] 写出 {data_out}")
    print(f"    总计 {total} 条 / {len(sections)} 板块 / {len(srcs_used)} 信源")
    for s in sections:
        print(f"      {s['name']:<16} {len(s['items'])} 条")
    return 0


def main():
    ap = argparse.ArgumentParser(description="RSS -> AI 日报数据 JSON")
    ap.add_argument("--hours", type=int, default=48,
                    help="回溯小时数（默认 48）")
    ap.add_argument("-o", "--output", help="输出 JSON 路径")
    ap.add_argument("--limit", type=int, default=None,
                    help="每板块最多保留条数")
    args = ap.parse_args()

    if args.output:
        out = Path(args.output)
        if not out.is_absolute():
            out = BASE / out
    else:
        out = BASE / "data" / f"{datetime.now(CST).strftime('%Y-%m-%d')}.json"

    print(f"抓取中（时间窗 {args.hours}h）...\n")
    return build(out, args.hours, args.limit)


if __name__ == "__main__":
    sys.exit(main())
