#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""AI 日报看板 · 服务器端一键更新入口（供 PyInstaller 打包成 exe）

流程：抓取 -> 生成 -> 归档 -> 校验 -> 清理
与开发机的 更新看板.cmd 等价，但把所有路径都改成「相对自身可执行文件」，
方便在服务器上任一目录运行。

用法：
    ai-briefing-update.exe                 # 默认输出到 exe 同级的 data\
    ai-briefing-update.exe --out D:\briefing\data
    ai-briefing-update.exe --hours 72 --keep-days 30

退出码：0=成功 1=失败（NSSM/计划任务可据此判断）
"""
import argparse
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# PyInstaller 打包后 __file__ 指向临时解压目录，必须用 sys.executable 的所在目录
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    # 打包后模块被收进 exe，无需额外 sys.path
else:
    APP_DIR = Path(__file__).resolve().parent
    # 开发模式：把项目根目录（fetch_rss.py / build.py 所在）加进搜索路径
    sys.path.insert(0, str(APP_DIR.parent))


def main():
    ap = argparse.ArgumentParser(description="AI 日报看板 · 服务器端更新")
    ap.add_argument("--out", default=None,
                    help="数据输出目录（默认 <exe所在目录>/data）")
    ap.add_argument("--hours", type=int, default=48,
                    help="RSS 回溯小时数（默认 48）")
    ap.add_argument("--keep-days", type=int, default=30,
                    help="归档保留天数（默认 30，0 表示不清理）")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve() if args.out else (APP_DIR / "data")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 延迟导入：让 PyInstaller 能正确收集依赖
    try:
        import json as _json
        from fetch_rss import build as fetch_build
        from build import build as render_html
    except ImportError as e:
        print(f"[x] 导入失败: {e}", file=sys.stderr)
        print("    打包时需同时包含 fetch_rss.py 与 build.py（见 build_exe.py）", file=sys.stderr)
        return 1

    today = date.today().isoformat()
    json_path = out_dir / "today.json"
    html_path = out_dir / "latest.html"
    archive_path = out_dir / f"{today}.html"

    print("=" * 56)
    print(f"  AI 日报看板 · 更新  ({datetime.now():%Y-%m-%d %H:%M:%S})")
    print("=" * 56)

    # ---- 1/5 抓取 ----
    print(f"\n[1/5] 抓取 RSS（时间窗 {args.hours}h）...")
    try:
        rc = fetch_build(json_path, args.hours, None)
    except Exception as e:
        print(f"[x] 抓取异常: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if rc != 0:
        print("[x] 抓取失败", file=sys.stderr)
        return 1

    # ---- 2/5 生成 ----
    print(f"\n[2/5] 生成 HTML...")
    try:
        data = _json.loads(json_path.read_text(encoding="utf-8"))
        # 版本戳：渲染页右上角显示"数据时间"，与 build.py 单独运行时的口径一致
        stamp = f'{data.get("date", today)} {datetime.now():%H:%M}'
        html = render_html(data, stamp)   # build.build(data, version) -> HTML 字符串
        html_path.write_text(html, encoding="utf-8")
        print(f"  [v] {html_path.name}  ({len(html):,} 字符)")
    except Exception as e:
        print(f"[x] 生成异常: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    # ---- 3/5 归档 ----
    print(f"\n[3/5] 归档当天副本...")
    try:
        shutil.copyfile(html_path, archive_path)
        print(f"  [v] {archive_path.name}")
    except OSError as e:
        print(f"  [!] 归档失败（不阻断）: {e}")

    # ---- 4/5 校验 ----
    print(f"\n[4/5] 校验产物...")
    text = html_path.read_text(encoding="utf-8")
    n_card = text.count('<article class="card')   # 前缀匹配：class 现为 "card reveal [wide]"
    n_sec = text.count('<section class="section"')
    n_bad = text.count("\ufffd")
    CN = re.compile(r"[\u4e00-\u9fff]")
    LT = re.compile(r"[A-Za-z]")
    titles = re.findall(r'<h3 class="card-title">(.*?)</h3>', text)
    en = [t for t in titles
          if len(CN.findall(t)) / max(len(t), 1) < 0.15 and len(LT.findall(t)) >= 8]
    h1 = re.search(r"<h1>(.*?)</h1>", text)
    h1 = re.sub(r"<[^>]+>", "", h1.group(1)) if h1 else "?"

    print(f"  卡片 {n_card} 张 / 板块 {n_sec} 个 / 乱码 {n_bad} 处 / 英文 {len(en)} 条")
    print(f"  主标题: {h1}")

    problems = []
    if n_card < 15:
        problems.append(f"卡片过少({n_card})")
    if n_sec < 4:
        problems.append(f"板块过少({n_sec})")
    if n_bad:
        problems.append(f"乱码({n_bad})")
    if en:
        problems.append(f"英文标题({len(en)})")
    if problems:
        print(f"\n[x] 校验未通过: {'; '.join(problems)}", file=sys.stderr)
        return 1

    # ---- 5/5 清理 ----
    if args.keep_days > 0:
        print(f"\n[5/5] 清理 {args.keep_days} 天前的归档...")
        cutoff = date.today() - timedelta(days=args.keep_days)
        arch_re = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.html$")
        removed = 0
        freed = 0
        for p in sorted(out_dir.iterdir()):
            if not p.is_file():
                continue
            m = arch_re.match(p.name)
            if not m:
                continue
            try:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            if d < cutoff:
                try:
                    size = p.stat().st_size
                    p.unlink()
                    removed += 1
                    freed += size
                except OSError as e:
                    print(f"  [!] 删除失败 {p.name}: {e}")
        print(f"  清理 {removed} 份，释放 {freed / 1024:.1f} KB" if removed
              else "  无需清理")
    else:
        print(f"\n[5/5] 跳过清理（--keep-days 0）")

    print()
    print("=" * 56)
    print(f"[v] 完成！产物: {html_path}")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
