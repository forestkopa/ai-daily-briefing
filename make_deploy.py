# -*- coding: utf-8 -*-
"""生成「全量部署包」——首次上线用，含 exe 备用方案。

用法：
    python make_deploy.py

产物：dist_package/ai-briefing-deploy.zip
     解压得到 ai-briefing-deploy/ 文件夹，整个拷到服务器即可。

与 make_update.py 的分工：
    make_deploy.py  首次部署（大，含 exe + nssm）
    make_update.py  日常增量更新（~31 KB，只替换源文件）
"""
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEPLOY = ROOT / "deploy"
PKG_EXTRA = ROOT / "dist_package"          # preflight.ps1 / add-ingress.ps1 由 tools/ 生成到此
PKG_DIR = ROOT / "dist_package" / "ai-briefing-deploy"
ZIP_PATH = ROOT / "dist_package" / "ai-briefing-deploy.zip"

# 包内文件清单：源路径 -> 包内文件名
# 注意 deploy-python.ps1 / deploy-nssm.ps1 必须保持 UTF-8 BOM（PS 5.1 中文才不乱码），
# 这里直接 shutil.copy2 原样复制，不做任何转码。
FILES = [
    (PKG_EXTRA / "preflight.ps1",   "preflight.ps1"),
    (PKG_EXTRA / "add-ingress.ps1", "add-ingress.ps1"),
    (DEPLOY / "diag-502.ps1",       "diag-502.ps1"),
    (DEPLOY / "deploy-python.ps1",  "deploy-python.ps1"),
    (DEPLOY / "deploy-nssm.ps1",    "deploy-nssm.ps1"),
    (DEPLOY / "server.js",          "server.js"),
    (DEPLOY / "cli.py",             "cli.py"),
    (ROOT / "fetch_rss.py",         "fetch_rss.py"),
    (ROOT / "build.py",             "build.py"),
    (ROOT / "clean_cache.py",       "clean_cache.py"),
    (DEPLOY / "部署手册.md",         "部署手册.md"),
    (DEPLOY / "Cloudflare_操作清单.md", "Cloudflare_操作清单.md"),
    (DEPLOY / "dist" / "ai-briefing-update.exe", "ai-briefing-update.exe"),
]

# nssm.exe：优先用包内的，否则从常见路径找
NSSM_CANDIDATES = [
    DEPLOY / "nssm.exe",
    ROOT / "nssm.exe",
    Path(r"C:\nssm\nssm.exe"),
]


def main():
    print("=" * 60)
    print("  打包 AI 日报看板 · 全量部署包")
    print("=" * 60)

    missing = []
    for src, _arc in FILES:
        if not src.exists():
            missing.append(src)
    if missing:
        for m in missing:
            print(f"[x] 缺少: {m}")
        return 1

    nssm = next((c for c in NSSM_CANDIDATES if c.exists()), None)
    if not nssm:
        print("[x] 找不到 nssm.exe（放在 deploy\\ 或 C:\\nssm\\）")
        return 1

    # ---- 重建目录 ----
    if PKG_DIR.exists():
        shutil.rmtree(PKG_DIR)
    PKG_DIR.mkdir(parents=True)

    # ---- 复制文件（原样，保 BOM）----
    for src, arc in FILES:
        shutil.copy2(src, PKG_DIR / arc)
    shutil.copy2(nssm, PKG_DIR / "nssm.exe")

    # ---- 附一份极简上手说明 ----
    readme = """# AI 日报看板 · 部署包

## 最快路径（4 步）

1. 把整个 `ai-briefing-deploy` 文件夹拷到服务器，如 `D:\\ai-briefing-deploy\\`
2. **管理员** PowerShell，`cd` 进去，**先自检**：
   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass -Force
   .\\preflight.ps1
   ```
   它会逐项报告「已就绪 / 需注意 / 必须先解决」，标红的先解决掉。
3. **一键部署**：
   ```powershell
   .\\deploy-python.ps1
   ```
4. **配域名**（只做这一次，以后改代码都不用再管）：
   ```powershell
   .\\add-ingress.ps1 -Hostname daily.forestkopa.top -Port 5190
   ```
   然后去 Cloudflare 后台加一条 CNAME —— 详见 `Cloudflare_操作清单.md`。

## 详细步骤 / 排错

看 **`部署手册.md`**（同目录）。第 2 章讲 Python 版本坑，第 5 章讲页面刷新按钮，
第 6 章讲以后怎么增量更新。

## 文件说明

| 文件 | 作用 |
|---|---|
| `preflight.ps1` | **部署前自检**（只读，随便跑） |
| `deploy-python.ps1` | **推荐**：一键部署（venv 模式，服务器需有 Python 3.6+） |
| `add-ingress.ps1` | **自动配隧道 ingress**（免手工改 YAML，带校验与回滚） |
| `diag-502.ps1` | **域名打不开时排障**（只读，定位 502 是"服务没起"还是"回源配错"） |
| `deploy-nssm.ps1` | 备用：exe 模式部署（免 Python） |
| `server.js` | 静态服务 + 刷新接口（Node，零依赖） |
| `cli.py` | 取数器入口 |
| `fetch_rss.py` / `build.py` / `clean_cache.py` | 抓取 / 渲染 / 清理 |
| `ai-briefing-update.exe` | 备用取数器（8 MB 单文件，免 Python） |
| `nssm.exe` | Windows 服务管理器 |
| `部署手册.md` | 完整手册 |
| `Cloudflare_操作清单.md` | **Cloudflare 侧要动什么**（第一次配完就不用再看） |

> 与已有的 kanban 服务完全隔离：服务名/端口/任务名都带 `ai-briefing` 前缀。
> 唯一共用的是同一条 cloudflared 隧道 —— 改 ingress 后重启会让 kanban 闪断 3~5 秒。
"""
    (PKG_DIR / "README.md").write_text(readme, encoding="utf-8")

    # ---- 打 zip ----
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(PKG_DIR.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(PKG_DIR.parent))

    print()
    for src, arc in FILES + [(nssm, "nssm.exe"), (PKG_DIR / "README.md", "README.md")]:
        p = PKG_DIR / arc
        print(f"  {p.stat().st_size:>12,} B  {arc}")
    size = ZIP_PATH.stat().st_size
    print()
    print(f"  产物: {ZIP_PATH}")
    print(f"  体积: {size:,} B ({size/1024/1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
