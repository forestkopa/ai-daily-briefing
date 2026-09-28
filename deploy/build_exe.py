#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""把服务器端 cli.py 打包成单文件 exe（PyInstaller）。

在开发机上运行：
    "C:/Users/Administrator/.workbuddy/binaries/python/envs/rss/Scripts/python.exe" build_exe.py

产物：
    deploy\dist\ai-briefing-update.exe

打包要点：
  - 单文件（--onefile）：服务器上一个 exe 就能跑，免装 Python
  - 隐藏导入 feedparser 的子模块（它动态 import，PyInstaller 扫不到）
  - 用 UTF-8 源码，避免 Windows 默认 GBK 导致的 SyntaxError
  - 输出到 deploy/dist/，不污染项目根
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # deploy/
ROOT = HERE.parent                              # ai-daily-briefing/
DIST = HERE / "dist"
WORK = HERE / "build"

EXE_NAME = "ai-briefing-update"


def main():
    print("=" * 60)
    print("  打包 AI 日报看板更新器（单文件 exe）")
    print("=" * 60)

    # ---- 前置检查 ----
    for f in ("cli.py",):
        if not (HERE / f).exists():
            print(f"[x] 缺少 {HERE / f}", file=sys.stderr)
            return 1
    for f in ("fetch_rss.py", "build.py"):
        if not (ROOT / f).exists():
            print(f"[x] 缺少 {ROOT / f}", file=sys.stderr)
            return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[x] PyInstaller 未安装。先运行：", file=sys.stderr)
        print('    pip install pyinstaller', file=sys.stderr)
        return 1

    # ---- 清理旧产物 ----
    for d in (DIST, WORK):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    # ---- 组装 PyInstaller 参数 ----
    # --paths ROOT：让 cli.py 能 import 到 fetch_rss / build
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",                     # 保留控制台，方便看日志（NSSM 可捕获）
        "--name", EXE_NAME,
        "--distpath", str(DIST),
        "--workpath", str(WORK),
        "--specpath", str(HERE),
        "--noconfirm",
        "--clean",
        "--paths", str(ROOT),
        # feedparser 动态导入这些子模块，需显式声明
        "--hidden-import", "feedparser",
        "--hidden-import", "feedparser.encodings",
        "--hidden-import", "feedparser.html",
        "--hidden-import", "feedparser.http",
        "--hidden-import", "feedparser.mixin",
        "--hidden-import", "feedparser.namespaces",
        "--hidden-import", "feedparser.parsers",
        "--hidden-import", "feedparser.sanitizer",
        "--hidden-import", "feedparser.urls",
        "--hidden-import", "sgmllib",
        # 排除用不到的重型库，压缩体积
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        "--exclude-module", "distutils",
        "--exclude-module", "email.tests",
        "--exclude-module", "PIL",
        "--exclude-module", "numpy",
        str(HERE / "cli.py"),
    ]

    print("\n[i] PyInstaller 命令：")
    print("    " + " ".join(cmd[:8]) + " ...")
    print("\n[i] 打包中（约 30-90 秒）...\n")

    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")

    # PyInstaller 日志量大，只在失败时全量输出
    if r.returncode != 0:
        print("[x] 打包失败，输出如下：", file=sys.stderr)
        print(r.stdout[-6000:] if r.stdout else "(no stdout)", file=sys.stderr)
        print(r.stderr[-4000:] if r.stderr else "(no stderr)", file=sys.stderr)
        return 1

    exe = DIST / f"{EXE_NAME}.exe"
    if not exe.exists():
        print(f"[x] 未找到产物 {exe}", file=sys.stderr)
        return 1

    size_mb = exe.stat().st_size / 1024 / 1024
    print("=" * 60)
    print(f"[v] 打包成功")
    print(f"    产物: {exe}")
    print(f"    体积: {size_mb:.1f} MB")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
