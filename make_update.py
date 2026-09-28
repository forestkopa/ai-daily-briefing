# -*- coding: utf-8 -*-
"""生成「增量更新包」——只包含需要替换的源文件，不含数据/venv/配置。

用法：
    python make_update.py                 # 打包全部源文件
    python make_update.py --only build.py  # 只打包指定文件（更快）

产物：dist_package/ai-briefing-update.zip
     内含 update.ps1 + 需要替换的文件 + 说明
"""
import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 服务器上会被替换的源文件（相对项目根的路径 -> 包内路径）
SERVER_FILES = {
    "fetch_rss.py":     "fetch_rss.py",
    "build.py":         "build.py",
    "clean_cache.py":   "clean_cache.py",
    "deploy/cli.py":    "cli.py",
    "deploy/server.js": "server.js",
}

# 服务器上【绝不覆盖】的东西（安全声明，也用于自检）
NEVER_TOUCH = ["data/", "venv/", "logs/", "*.log", "admin.password"]


UPDATE_PS1 = r'''<#
.SYNOPSIS
    AI 日报看板 · 增量更新（服务器端运行）

.DESCRIPTION
    只替换源文件，不动 data/ (数据) 、venv/ (环境) 、logs/ (日志)。

    流程：定位服务真实目录 -> 备份 -> 替换 -> 需要时重启服务 -> 重新生成页面。
    最后一步是为了让 UI / 模板改动【立刻可见】，不然要等次日 08:30 定时任务。

    用法：
      1. 把解压出来的这些文件放到服务器任意目录
      2. 管理员 PowerShell 运行：
           .\update.ps1
         或指定安装目录：
           .\update.ps1 -InstallDir "D:\ai-daily-briefing"
         只想替换文件、不做后续动作：
           .\update.ps1 -NoRestart -NoRegen
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "D:\ai-daily-briefing",
    [switch]$NoRestart,
    [switch]$NoRegen
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$SvcName = "ai-briefing-server"

function Say  ($m) { Write-Host $m }
function Ok   ($m) { Write-Host "[v] $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "[!] $m" -ForegroundColor Yellow }
function Fail ($m) { Write-Host "[x] $m" -ForegroundColor Red }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RealDir = $null          # 服务实际使用的目录（可能 != $InstallDir）
$RegenOk = $false

Say "=============================================================="
Say "  AI 日报看板 · 增量更新"
Say "=============================================================="
Say ""

if (-not (Test-Path $InstallDir)) {
    Fail "安装目录不存在: $InstallDir"
    Say "    用 -InstallDir 指定正确路径。"
    exit 1
}
Ok "安装目录: $InstallDir"

# ================================================================== 0. 定位服务真实目录
# 【为什么必须做这步】服务的工作目录可能 != $InstallDir：
#   - 用 deploy-python.ps1 装的 -> AppDirectory = $InstallDir
#   - 用 deploy-nssm.ps1 装的   -> 也可能指向部署包所在目录
# 而 server.js / data\ 是【按工作目录】找的，只替换 $InstallDir 会出现
# "替换成功但页面/服务没变" 的假成功。先查清楚，再决定替换到哪。
Say ""
Say "[0/7] 定位服务实际使用的目录..."
$svc = Get-CimInstance Win32_Service -Filter "Name='$SvcName'" -ErrorAction SilentlyContinue
if ($svc) {
    Ok "服务 $SvcName 存在（状态: $($svc.State)）"

    # AppDirectory 优先；取不到就从 PathName 里反推 nssm.exe 所在目录
    $svcDir = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\$SvcName" `
                -Name AppDirectory -ErrorAction SilentlyContinue).AppDirectory
    if (-not $svcDir -and $svc.PathName) {
        $exePath = $svc.PathName.Trim('"').Split('"')[0].Trim('"')
        if (Test-Path $exePath) { $svcDir = Split-Path -Parent $exePath }
    }

    if ($svcDir -and (Test-Path $svcDir)) {
        # 判定依据：该目录下有 server.js 才认作服务目录
        if (Test-Path (Join-Path $svcDir "server.js")) {
            $RealDir = (Resolve-Path $svcDir).Path
            Ok "服务实际目录: $RealDir"
            if ($RealDir.TrimEnd('\') -ne (Resolve-Path $InstallDir).Path.TrimEnd('\')) {
                Warn "与应用目录 $InstallDir 不一致！"
                Say "     -> 本次将【同时】替换两处，确保服务真正用到新文件。"
            }
        } else {
            Warn "推断出的服务目录没有 server.js，忽略: $svcDir"
        }
    } else {
        Warn "无法确定服务目录，只替换 $InstallDir"
    }
} else {
    Warn "服务 $SvcName 未注册 —— 可能还没跑过部署脚本。"
    Say "     -> 仅替换文件，跳过重启。"
}

# 汇总要去重的替换目标目录
$DestDirs = @($InstallDir)
if ($RealDir -and ($RealDir.TrimEnd('\') -ne (Resolve-Path $InstallDir).Path.TrimEnd('\'))) {
    $DestDirs += $RealDir
}

# ---- 备份当前版本（只备份源文件，极小）----
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$bak = Join-Path $InstallDir "backup\$stamp"
New-Item -ItemType Directory -Force -Path $bak | Out-Null

$srcFiles = @("fetch_rss.py","build.py","clean_cache.py","cli.py","server.js")
$backed = 0
foreach ($f in $srcFiles) {
    $cur = Join-Path $InstallDir $f
    if (Test-Path $cur) {
        Copy-Item $cur (Join-Path $bak $f) -Force
        $backed++
    }
}
Ok "已备份 $backed 个源文件到 backup\$stamp"

# ---- 逐文件替换 + 校验 ----
Say ""
Say "替换文件..."
$updated = @()
$missing = @()
foreach ($f in $srcFiles) {
    $new = Join-Path $ScriptDir $f
    if (-not (Test-Path $new)) { $missing += $f; continue }

    $anyOk = $false
    foreach ($dir in $DestDirs) {
        $dst = Join-Path $dir $f
        # 备份该目录下的现有版本（两处目录各自留档，回滚时互不干扰）
        if (Test-Path $dst) {
            $bakDir = Join-Path $dir "backup\$stamp"
            New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
            Copy-Item $dst (Join-Path $bakDir $f) -Force -ErrorAction SilentlyContinue
        }
        try {
            Copy-Item $new $dst -Force -ErrorAction Stop
            $sz = (Get-Item $dst).Length
            Ok ("  {0,-18} -> {1}  ({2:N0} B)" -f $f, $dir, $sz)
            $anyOk = $true
        } catch {
            Fail ("  {0,-18} -> {1} 覆盖失败: {2}" -f $f, $dir, $_.Exception.Message)
            Warn "    可能被占用。先停服务再重试：& `"$($svcDir)\nssm.exe`" stop $SvcName"
        }
    }
    if ($anyOk) { $updated += $f }
}
if ($missing.Count -gt 0) {
    Warn "包里没有这些文件（视为未变更，跳过）: $($missing -join ', ')"
}

# ---- 找 nssm.exe（顺序：服务目录 -> 脚本目录 -> 安装目录 -> 常见路径）----
function Find-Nssm {
    param([string]$SvcName, [string]$ScriptDir, [string]$InstallDir, [string]$SvcDir)
    $cands = @()
    if ($SvcDir)     { $cands += (Join-Path $SvcDir "nssm.exe") }
    $cands += (Join-Path $ScriptDir "nssm.exe")      # <= 最容易命中：解压目录里就带着
    $cands += (Join-Path $InstallDir "nssm.exe")
    $cands += "C:\nssm\nssm.exe"
    $cands += "C:\ProgramData\chocolatey\bin\nssm.exe"
    foreach ($c in $cands) { if ($c -and (Test-Path $c)) { return (Resolve-Path $c).Path } }

    # 最后兜底：从注册表服务的 ImagePath 反查
    $ip = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\$SvcName" `
            -Name ImagePath -ErrorAction SilentlyContinue).ImagePath
    if ($ip) {
        $p = $ip.Trim('"').Split('"')[0].Trim('"')
        if (Test-Path $p) { return (Resolve-Path $p).Path }
    }
    return $null
}

$nssm = Find-Nssm -SvcName $SvcName -ScriptDir $ScriptDir -InstallDir $InstallDir -SvcDir $svcDir
$needRestart = ($updated -contains "server.js")

Say ""
if ($needRestart -and -not $NoRestart) {
    if (-not $svc) {
        Warn "服务 $SvcName 未注册，无法重启。"
        Say "     -> 首次部署请先跑部署脚本（deploy-python.ps1 或 deploy-nssm.ps1）。"
    } elseif (-not $nssm) {
        Warn "找不到 nssm.exe，且服务已注册。请手动重启："
        Say "     Get-Service $SvcName | Restart-Service"
        Say "     （或把 nssm.exe 放到本脚本同目录后重跑）"
    } else {
        Say "server.js 有更新，用 $nssm 重启服务..."
        & cmd /c "`"$nssm`" restart $SvcName 2>nul" | Out-Null
        Start-Sleep -Seconds 3
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:5190/healthz" -UseBasicParsing -TimeoutSec 10
            Ok "服务已重启，探活 HTTP $($r.StatusCode)"
        } catch {
            Fail "探活失败，看日志: Get-Content `"$InstallDir\logs\server-err.log`" -Tail 30"
        }
    }
} elseif ($needRestart) {
    Warn "server.js 已更新，但指定了 -NoRestart，请手动重启服务"
} else {
    Say "未涉及 server.js，无需重启服务"
}

# ---- 重新生成页面（关键！否则改了 build.py 也看不到变化）----
# 【为什么必须做】update.ps1 只替换代码，页面 HTML 是【上次生成时】的产物。
# 不重跑一次，用户改完 UI / 模板后打开页面还是旧的，会误判"更新失败"。
Say ""
if ($NoRegen) {
    Warn "已跳过页面重新生成（-NoRegen）"
    Say "     -> 手动跑：& `"$InstallDir\cli.py`" 或 venv\Scripts\python.exe cli.py --out data"
} else {
    Say "重新生成页面（让新代码立即生效）..."
    $dataDir = $null
    foreach ($d in $DestDirs) {
        if (Test-Path (Join-Path $d "data")) { $dataDir = Join-Path $d "data"; break }
    }
    if (-not $dataDir) { $dataDir = Join-Path $InstallDir "data" }

    # 依次尝试：安装目录的 venv -> 服务目录的 venv -> exe
    $regen = $null
    $regenArgs = @()
    foreach ($d in $DestDirs) {
        $vpy = Join-Path $d "venv\Scripts\python.exe"
        if (Test-Path $vpy) { $regen = $vpy; $regenArgs = @((Join-Path $d "cli.py")); break }
    }
    if (-not $regen) {
        foreach ($d in $DestDirs) {
            $exe = Join-Path $d "ai-briefing-update.exe"
            if (Test-Path $exe) { $regen = $exe; $regenArgs = @(); break }
        }
    }

    if (-not $regen) {
        Warn "找不到 venv 的 python.exe，也找不到 ai-briefing-update.exe，无法自动重新生成。"
        Say "     -> 页面会在下次定时任务（08:30）时用新代码重新生成。"
        Say "     -> 想立刻生效，手动跑 cli.py 或 exe（见 更新说明.md）。"
    } else {
        Say "      用: $regen"
        Push-Location $InstallDir
        try {
            & $regen @regenArgs --out $dataDir --hours 48 --keep-days 30
            if ($LASTEXITCODE -eq 0) {
                $RegenOk = $true
                Ok "页面已重新生成"
            } else {
                Warn "重新生成返回非零（$LASTEXITCODE），但代码已更新，不影响下次定时任务。"
            }
        } catch {
            Warn "重新生成异常: $($_.Exception.Message)"
        } finally {
            Pop-Location
        }
    }
}

Say ""
Say "=============================================================="
Ok "更新完成"
Say "=============================================================="
Say ""
Say "  验证更新效果（看页面是不是新样式）："
Say "      Select-String -Path `"$dataDir\latest.html`" -Pattern 'F2704F','4px 4px 0' -SimpleMatch | Select-Object -First 2"
Say "      浏览器打开 http://127.0.0.1:5190/ 并 Ctrl+F5 强制刷新"
Say ""
Say "  回滚方法（如需，把 <目录> 换成实际路径）："
foreach ($d in $DestDirs) {
    Say "      Copy-Item `"$d\backup\$stamp\*`" `"$d\`" -Force"
}
Say ""
'''


# .cmd 双击入口 —— 刻意用 .cmd 而非 .ps1：
# .cmd 不受 PowerShell ExecutionPolicy 限制，服务器默认 Restricted 也能跑
# 内容保持纯 ASCII（中文标题由 update.ps1 负责输出），避免 cmd 代码页问题
UPDATE_CMD = r'''@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================================
echo   AI Daily Briefing - Incremental Update
echo ==============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" %*
echo.
echo Press any key to close...
pause >nul
'''

UPDATE_README = r'''# AI 日报看板 · 增量更新包

## 怎么用（服务器上）

1. 把 zip 解压到服务器任意目录（**不要**解压到 `D:\ai-daily-briefing` 里面）
2. **双击 `更新.cmd`** —— 完事

> 或者管理员 PowerShell 里跑：
> ```powershell
> powershell -ExecutionPolicy Bypass -File .\update.ps1
> ```
> 安装目录不是默认值时：
> ```powershell
> powershell -ExecutionPolicy Bypass -File .\update.ps1 -InstallDir "D:\你的路径"
> ```

## 它做了什么

| 步骤 | 说明 |
|---|---|
| 0 | **定位服务真实目录** —— 服务的工作目录可能不是你传的 `-InstallDir`，脚本会自动查出并同时替换两处 |
| 1 | 备份现有 5 个源文件到 `<目录>\backup\<时间戳>\` |
| 2 | 替换 `fetch_rss.py` / `build.py` / `clean_cache.py` / `cli.py` / `server.js` |
| 3 | 若 `server.js` 有变 → 自动重启服务 + 探活 |
| 4 | **重新生成页面 HTML** —— 让 UI / 模板改动立刻可见 |

> ⚠️ 第 4 步很关键。以前只替换代码不重新生成，导致"改完 UI 打开页面还是旧样式"，
> 得干等到次日 08:30 定时任务才生效。

## 它绝不动什么

- ❌ `data\` —— 你的日报数据（除了第 4 步重新生成 `latest.html`，这是刻意的）
- ❌ `venv\` —— Python 环境（所以更新包只有 30 多 KB）
- ❌ `logs\` —— 日志

## 回滚

```powershell
Copy-Item "D:\ai-daily-briefing\backup\<时间戳>\*" "D:\ai-daily-briefing\" -Force
```

## 更新后要不要重启服务？

**不用管，脚本已经替你做完。** 它会自己判断：

- 改了 `server.js` → 自动重启服务
- 改了取数/模板脚本 → 自动重新生成页面（立刻可见，不用等 08:30）
- 服务没注册（首次部署前）→ 跳过重启，只替换文件

## 更新完怎么验证？

```powershell
# 页面里应该有新 UI 的珊瑚色标记
Select-String -Path "D:\ai-daily-briefing\data\latest.html" -Pattern 'F2704F','4px 4px 0' -SimpleMatch | Select-Object -First 2
```

有输出 = 新样式生效。浏览器 `Ctrl+F5` 强制刷新看效果。
'''


def main():
    ap = argparse.ArgumentParser(description="生成 AI 日报看板增量更新包")
    ap.add_argument("--only", nargs="*", default=None,
                    help="只打包指定文件名（如 build.py），默认全部")
    ap.add_argument("--out", default=None, help="输出 zip 路径")
    args = ap.parse_args()

    out_dir = ROOT / "dist_package"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = Path(args.out) if args.out else out_dir / "ai-briefing-update.zip"

    # 计算要打包的文件
    targets = {}
    for rel, arc in SERVER_FILES.items():
        src = ROOT / rel
        if not src.exists():
            print(f"[!] 跳过（不存在）: {rel}")
            continue
        if args.only:
            if arc not in args.only and src.name not in args.only:
                continue
        targets[arc] = src

    if not targets:
        print("[x] 没有要打包的文件")
        return 1

    # 安全检查：绝不打包数据/环境/日志
    for arc, src in targets.items():
        s = str(src).lower()
        for bad in ("\\data\\", "/data/", "\\venv\\", "/venv/", "\\logs\\", "/logs/"):
            assert bad not in s, f"拒绝打包敏感路径: {src}"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        # update.ps1（写 UTF-8 BOM 前缀，PS 5.1 才不乱码）
        z.writestr("update.ps1", b"\xef\xbb\xbf" + UPDATE_PS1.encode("utf-8"))
        # 更新.cmd —— 不加 BOM（cmd.exe 会把 BOM 当命令的一部分报错）
        # 内容全 ASCII + chcp 65001，避免中文编码问题
        z.writestr("更新.cmd", UPDATE_CMD.encode("ascii"))
        z.writestr("更新说明.md", b"\xef\xbb\xbf" + UPDATE_README.encode("utf-8"))
        for arc, src in sorted(targets.items()):
            z.write(src, arc)

    print("=" * 56)
    print("  增量更新包已生成")
    print("=" * 56)
    with zipfile.ZipFile(zip_path) as z:
        for i in z.infolist():
            print(f"  {i.file_size:>10,} B  {i.filename}")
    size = zip_path.stat().st_size
    print()
    print(f"  产物: {zip_path}")
    print(f"  体积: {size:,} B ({size/1024:.1f} KB)")
    print()
    print("  服务器端用法：解压后管理员 PowerShell 运行 .\\update.ps1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
