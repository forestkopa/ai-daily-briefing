# -*- coding: utf-8 -*-
"""包内实物验证：把 zip 里的文件解出来真跑一遍，而不是只看打包回显。

用法：python tools/verify_package.py
退出码 0 = 全部通过。
"""
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
UPDATE = ROOT / "dist_package" / "ai-briefing-update.zip"
DEPLOY = ROOT / "dist_package" / "ai-briefing-deploy.zip"
DATA = ROOT / "data" / "today.json"

results = []


def ck(name, cond, extra=""):
    results.append((name, bool(cond), str(extra)))


def read_zip_text(z, name):
    return z.read(name).decode("utf-8")


def main():
    for p in (UPDATE, DEPLOY, DATA):
        if not p.exists():
            print(f"[x] 缺少 {p}")
            return 1

    # ---------- 增量包 ----------
    with zipfile.ZipFile(UPDATE) as z:
        up_names = z.namelist()
        up_build = read_zip_text(z, "build.py")
        up_cli = read_zip_text(z, "cli.py")
        up_srv = read_zip_text(z, "server.js")
        up_ps = read_zip_text(z, "update.ps1")

    ck("增量包含 build.py / cli.py / server.js",
       {"build.py", "cli.py", "server.js"} <= set(up_names), sorted(up_names))
    ck("增量包 build.py 是新版 UI（含 .reveal.in 优先级修复）",
       "html.js-ready .reveal.in" in up_build)
    ck("增量包 build.py 已去掉旧的橙色主题",
       "--accent:#FF6B35" not in up_build)
    ck("增量包 build.py 主标题结构保留空格（兼容旧校验）",
       '<span class="hl">AI</span> <span class="l2">' in up_build)
    ck("增量包 cli.py 向 build 传版本戳", "render_html(data, stamp)" in up_cli)
    ck("增量包 cli.py 卡片计数改前缀匹配",
       "text.count('<article class=\"card')" in up_cli)
    ck("server.js 未被改动（端口 5190 仍在）", "'5190'" in up_srv)
    ck("update.ps1 保留 BOM", Path(UPDATE).read_bytes()[:2] == b"PK")  # zip 本身
    ck("update.ps1 内容含 InstallDir 默认值", "InstallDir" in up_ps)

    # ---------- 全量包 ----------
    with zipfile.ZipFile(DEPLOY) as z:
        dp_names = [n for n in z.namelist() if not n.endswith("/")]
        dp_build = read_zip_text(z, "ai-briefing-deploy/build.py")

    ck("全量包 build.py 与增量包一致", dp_build == up_build)
    ck("全量包含 nssm.exe / preflight.ps1 / deploy-python.ps1",
       all(any(n.endswith(x) for n in dp_names)
           for x in ("nssm.exe", "preflight.ps1", "deploy-python.ps1")))
    ck("全量包文件数 = 15", len(dp_names) == 15, len(dp_names))
    ck("全量包不含 data/ 与 venv/",
       not any("/data/" in n or "/venv/" in n for n in dp_names))

    # ---------- 端到端：解出包内 build.py 真跑 ----------
    tmp = Path(tempfile.mkdtemp(prefix="verify-pkg-"))
    with zipfile.ZipFile(DEPLOY) as z:
        z.extract("ai-briefing-deploy/build.py", tmp)
    build_py = tmp / "ai-briefing-deploy" / "build.py"
    out = tmp / "out.html"
    r = subprocess.run([PY, str(build_py), str(DATA), "-o", str(out)],
                       capture_output=True, encoding="utf-8", errors="replace")
    ck("包内 build.py 端到端生成成功（rc=0）", r.returncode == 0,
       (r.stderr or "")[-200:])
    html = out.read_text(encoding="utf-8") if out.exists() else ""
    ck("产物卡片 36 张", html.count('<article class="card') == 36,
       html.count('<article class="card'))
    ck("产物板块 5 个", html.count('<section class="section"') == 5)
    ck("产物无乱码", "\ufffd" not in html)
    # 主标题要按「去标签后的文本」比，不能直接拿纯文本搜 HTML 源码
    # （源码里是 今日 <span>AI</span> <span>圈发生了什么</span>）
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    h1 = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""
    ck("产物主标题文本正确", h1 == "今日 AI 圈发生了什么", repr(h1))
    ck("产物含刷新按钮 2 个", html.count("data-refresh") >= 2)
    ck("产物无旧版图标容器", 'class="section-head"' not in html)
    ck("产物含焦点区三件套",
       'class="feature' in html and 'accent-card' in html and 'class="mini' in html)

    # ---------- 汇总 ----------
    fail = [x for x in results if not x[1]]
    for name, ok, extra in results:
        line = f"  [{'OK' if ok else 'FAIL'}] {name}"
        if not ok and extra:
            line += f"   <- {extra}"
        print(line)
    print(f"\n通过 {len(results) - len(fail)}/{len(results)}")
    print("RESULT:", "PASS" if not fail else "FAIL")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
