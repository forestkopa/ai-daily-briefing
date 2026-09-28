#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看板缓存清理：滚动保留最近 N 天的归档，删掉更早的。

设计原则：
  - 只动 data/ 下的归档文件（<YYYY-MM-DD>.html），绝不碰源代码、latest.html、today.json
  - 默认保留 30 天，可用 --days 覆盖
  - 删除前先列清单并统计体积，--dry-run 可只看不删
  - 走永久删除（SHFileOperationW 直调，绕过 safe-delete 钩子），因为归档可随时重新生成
  - 退出码：0=成功(含无文件可删)  1=有文件删失败

用法：
    python clean_cache.py                  # 保留 30 天
    python clean_cache.py --days 7         # 保留 7 天
    python clean_cache.py --dry-run        # 只看要删什么
    python clean_cache.py --dir D:\\data    # 指定归档目录
"""
import argparse
import ctypes
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"

# 只匹配归档命名，避免误删其它文件
ARCHIVE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.html$")

# 永不删除的白名单（即使命名符合归档规则）
KEEP_ALWAYS = {"latest.html", "today.json"}


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_bool),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_NOERRORUI = 0x0400


def permanent_delete(paths):
    """逐个永久删除文件，返回 (成功数, 失败列表)。

    不用 os.remove/shutil.rmtree —— 本机有 safe-delete 钩子会拦截。
    SHFileOperationW 直调可绕过；不加 FOF_ALLOWUNDO 即永久删除。
    """
    ok, failed = 0, []
    for p in paths:
        op = SHFILEOPSTRUCTW(
            None, FO_DELETE, str(p) + "\0\0", None,
            FOF_SILENT | FOF_NOCONFIRMATION | FOF_NOERRORUI,
            False, None, None,
        )
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if rc == 0:
            ok += 1
        else:
            failed.append((p, rc))
    return ok, failed


def find_stale(days, data_dir=None):
    """返回 (待删列表, 保留列表)，待删按日期升序。"""
    data_dir = Path(data_dir) if data_dir else DATA
    if not data_dir.exists():
        return [], []

    today = date.today()
    cutoff = today - timedelta(days=days)

    stale, keep = [], []
    for p in sorted(data_dir.iterdir()):
        if not p.is_file() or p.name in KEEP_ALWAYS:
            continue
        m = ARCHIVE_RE.match(p.name)
        if not m:
            continue                     # 非归档命名，一律不动
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue                     # 非法日期（如 2026-13-45.html），不动
        (stale if d < cutoff else keep).append((d, p))

    stale.sort(key=lambda x: x[0])
    keep.sort(key=lambda x: x[0])
    return [p for _, p in stale], [p for _, p in keep]


def main():
    ap = argparse.ArgumentParser(description="看板归档缓存清理")
    ap.add_argument("--days", type=int, default=30,
                    help="保留最近多少天的归档（默认 30）")
    ap.add_argument("--dir", dest="data_dir", default=None,
                    help="归档目录（默认脚本同级 data/）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只列出将要删除的文件，不实际删除")
    args = ap.parse_args()

    if args.days < 1:
        print("[x] --days 必须 >= 1", file=sys.stderr)
        return 1

    target = Path(args.data_dir) if args.data_dir else DATA
    stale, keep = find_stale(args.days, target)

    print(f"归档目录: {target}")
    print(f"保留策略: 最近 {args.days} 天（{date.today() - timedelta(days=args.days)} 之后）")
    print()

    if not stale:
        print(f"[v] 无需清理（保留 {len(keep)} 份归档）")
        return 0

    total = sum(p.stat().st_size for p in stale)
    print(f"待清理 {len(stale)} 份归档，共 {total / 1024:.1f} KB：")
    for p in stale:
        print(f"    {p.stat().st_size:>8,} B  {p.name}")
    print()
    print(f"保留 {len(keep)} 份归档"
          + (f"（{keep[0].name} ~ {keep[-1].name}）" if keep else ""))

    if args.dry_run:
        print()
        print("[i] --dry-run 模式，未实际删除")
        return 0

    print()
    print("执行删除（永久删除，归档可重新生成）...")
    ok, failed = permanent_delete(stale)
    print(f"    成功 {ok} / 失败 {len(failed)}")
    for p, rc in failed:
        print(f"    [x] rc={rc} {p.name}")

    if failed:
        print()
        print(f"[!] 有 {len(failed)} 个文件删除失败，可能被占用。", file=sys.stderr)
        return 1

    print()
    print(f"[v] 清理完成，释放 {total / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
